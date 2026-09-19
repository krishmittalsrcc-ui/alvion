"""The edit. Turns approved clips into a finished ad.

Every choice here traces to a documented technique (knowledge/edit.md):
  - trims on measured speech, never round numbers
  - jump cuts on internal pauses for fast pacing, alternating a subtle punch-in
  - J-cuts: the next clip's sound arrives ~8 frames before its picture
  - an 8ms fade on every cut so audio never clicks
  - optional short crossfades only at clip boundaries, never at jump cuts
  - captions timed from speech but spelled from the approved script
  - music enters after the hook, ducks under voice, drops out for one silence beat
  - look: light blur -> fine temporal grain -> grade -> vignette (in that order)
  - two-pass loudness normalisation to -14 LUFS / -1 dBTP
"""
import difflib
import json
import os
import re

from . import media

FPS = 30
EDGE_FADE = 0.008          # per-cut audio fade, seconds
PRELAP = 0.25              # J-cut: sound before picture (~8 frames)
XFADE = 0.2                # smooth transition overlap at clip boundaries
MIN_SEG = 0.45

PACING = {                 # max internal pause kept (s), head air, tail air
    "natural": (None, 0.20, 0.30),
    "tight":   (0.60, 0.15, 0.22),
    "fast":    (0.35, 0.12, 0.18),
}

# Caption baseline (MarginV at 1920 tall) that clears each platform's UI overlay.
SAFE_MARGIN_V = {"tiktok": 400, "reels": 540, "shorts": 460, "meta": 480,
                 "youtube": 140, "other": 540}

LOOKS = {
    "none":  None,
    "phone": "gblur=sigma=0.35,noise=alls=5:allf=t,eq=saturation=0.96:contrast=1.02,"
             "vignette=angle=PI/6",
    "film":  "gblur=sigma=0.5,noise=alls=8:allf=t+u,eq=saturation=0.9:contrast=1.05:gamma=0.98,"
             "colorbalance=rs=0.03:gs=0.0:bs=-0.03,vignette=angle=PI/5",
}

ACCENT_ASS = "&H0036A6FF&"   # ALVION amber (#FFA636) in ASS BGR


class EditError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# planning the cut
# ---------------------------------------------------------------------------

def _keep_ranges(path, speaking, pacing, planned=None):
    """Which parts of a clip survive the edit."""
    info = media.probe(path)
    dur = float(info.get("duration") or 0)
    if dur <= 0:
        raise EditError("Unreadable clip: %s" % os.path.basename(path))
    max_gap, head_air, tail_air = PACING.get(pacing, PACING["natural"])

    if not speaking or not info.get("has_audio"):
        end = min(dur, float(planned)) if (planned and pacing != "natural") else dur
        return [(0.0, round(end, 3))], dur

    segs, _ = media.speech_segments(path)
    if not segs:
        return [(0.0, dur)], dur

    start = max(0.0, segs[0][0] - head_air)
    stop = min(dur, segs[-1][1] + tail_air)
    if max_gap is None:
        return [(round(start, 3), round(stop, 3))], dur

    # merge speech spans whose gap is short enough to keep
    groups = [[segs[0][0], segs[0][1]]]
    for a, b in segs[1:]:
        if a - groups[-1][1] <= max_gap:
            groups[-1][1] = b
        else:
            groups.append([a, b])
    ranges = []
    for i, (a, b) in enumerate(groups):
        lo = start if i == 0 else max(0.0, a - 0.08)
        hi = stop if i == len(groups) - 1 else min(dur, b + 0.08)
        ranges.append([lo, hi])
    # never keep a sliver — fold it into its neighbour
    merged = []
    for r in ranges:
        if merged and (r[1] - r[0] < MIN_SEG or merged[-1][1] - merged[-1][0] < MIN_SEG):
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(round(a, 3), round(b, 3)) for a, b in merged], dur


def plan_cut(shots, settings):
    """Build the ordered segment list with timeline positions."""
    pacing = settings.get("pacing", "natural")
    smooth = settings.get("transitions") == "smooth"
    punch = bool(settings.get("punch_in"))
    jcut = settings.get("jcut", True)

    segments, t, punch_flip = [], 0.0, False
    for si, shot in enumerate(shots):
        speaking = bool((shot.get("dialogue") or "").strip()) and not shot.get("mute_in_edit")
        ranges, dur = _keep_ranges(shot["clip_path"], speaking, pacing, shot.get("duration"))
        for ri, (a, b) in enumerate(ranges):
            new_clip = ri == 0 and si > 0
            overlap = XFADE if (smooth and new_clip) else 0.0
            if segments:
                t -= overlap
            # J-cut: pull this clip's sound in early, from its own head handle
            pre = 0.0
            if jcut and new_clip and not smooth and speaking:
                pre = min(PRELAP, a)
            use_punch = False
            if punch and speaking and pacing != "natural" and ri > 0:
                punch_flip = not punch_flip
                use_punch = punch_flip
            segments.append({
                "shot": si, "clip": shot["clip_path"], "in": a, "out": b,
                "dur": round(b - a, 3), "at": round(t, 3),
                "speaking": speaking, "mute": bool(shot.get("mute_in_edit")),
                "new_clip": new_clip, "xfade": overlap, "prelap": round(pre, 3),
                "punch": use_punch,
            })
            t += b - a
    return segments, round(t, 3)


# ---------------------------------------------------------------------------
# rendering pieces
# ---------------------------------------------------------------------------

def _render_video_seg(seg, W, H, out):
    vf = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (W, H, W, H)
    if seg["punch"]:
        sw, sh = int(W * 1.08) // 2 * 2, int(H * 1.08) // 2 * 2
        # faces live in the upper third — crop biased upward
        vf += ",scale=%d:%d,crop=%d:%d:(iw-%d)/2:(ih-%d)*0.35" % (sw, sh, W, H, W, H)
    vf += ",fps=%d,setsar=1,format=yuv420p" % FPS
    media.run_ffmpeg(["-ss", "%.3f" % seg["in"], "-t", "%.3f" % seg["dur"], "-i", seg["clip"],
                      "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                      "-y", out], capture=False)


def _render_audio_seg(seg, out):
    start = seg["in"] - seg["prelap"]
    d = seg["dur"] + seg["prelap"]
    info = media.probe(seg["clip"])
    if seg["mute"] or not info.get("has_audio"):
        media.run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "%.3f" % d,
                          "-c:a", "pcm_s16le", "-y", out], capture=False)
        return
    fade_in = max(EDGE_FADE, seg["prelap"] or 0.0, seg["xfade"] or 0.0)
    fade_out = max(EDGE_FADE, 0.0)
    af = ("aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
          "afade=t=in:st=0:d=%.3f,afade=t=out:st=%.3f:d=%.3f"
          % (fade_in, max(0.0, d - fade_out), fade_out))
    media.run_ffmpeg(["-ss", "%.3f" % start, "-t", "%.3f" % d, "-i", seg["clip"], "-vn",
                      "-af", af, "-c:a", "pcm_s16le", "-y", out], capture=False)


def _join_picture(seg_files, segments, out):
    """Chain segments: hard concat, or xfade where a transition overlaps."""
    if not any(s["xfade"] for s in segments):
        lst = out + ".txt"
        with open(lst, "w") as f:
            for p in seg_files:
                f.write("file '%s'\n" % p.replace("'", "'\\''"))
        media.run_ffmpeg(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-y", out],
                         capture=False)
        return
    args, chain = [], []
    for p in seg_files:
        args += ["-i", p]
    for i in range(len(seg_files)):
        chain.append("[%d:v]settb=AVTB,setpts=PTS-STARTPTS[s%d]" % (i, i))
    cur, acc = "s0", segments[0]["dur"]
    for i in range(1, len(seg_files)):
        nxt, lab = "s%d" % i, "j%d" % i
        o = segments[i]["xfade"]
        if o:
            chain.append("[%s][%s]xfade=transition=fade:duration=%.3f:offset=%.3f[%s]"
                         % (cur, nxt, o, max(0.01, acc - o), lab))
            acc += segments[i]["dur"] - o
        else:
            chain.append("[%s][%s]concat=n=2:v=1:a=0[%s]" % (cur, nxt, lab))
            acc += segments[i]["dur"]
        cur = lab
    media.run_ffmpeg(args + ["-filter_complex", ";".join(chain), "-map", "[%s]" % cur,
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                             "-pix_fmt", "yuv420p", "-y", out], capture=False)


def _mix_voice(audio_files, segments, total, out):
    args, chain, labels = [], [], []
    for i, (p, s) in enumerate(zip(audio_files, segments)):
        args += ["-i", p]
        delay = max(0, int(round((s["at"] - s["prelap"]) * 1000)))
        chain.append("[%d:a]adelay=%d|%d[a%d]" % (i, delay, delay, i))
        labels.append("[a%d]" % i)
    chain.append("%samix=inputs=%d:normalize=0:dropout_transition=0,atrim=duration=%.3f[v]"
                 % ("".join(labels), len(labels), total))
    media.run_ffmpeg(args + ["-filter_complex", ";".join(chain), "-map", "[v]",
                             "-c:a", "pcm_s16le", "-ar", "48000", "-y", out], capture=False)


def _mix_music(voice, music, total, hook_end, silence_at, gain, out):
    """Music enters after the hook, ducks under voice, drops out for one silence beat."""
    vol = "%.3f*min(1\\,max(0\\,(t-%.3f)/0.6))" % (gain, hook_end)
    if silence_at is not None:
        vol += "*(1-between(t\\,%.3f\\,%.3f))" % (silence_at, silence_at + 0.45)
    chain = [
        "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
        "atrim=duration=%.3f,asetpts=PTS-STARTPTS,volume='%s':eval=frame,"
        "afade=t=out:st=%.3f:d=0.8[mus]" % (total, vol, max(0, total - 0.8)),
        "[0:a]asplit=2[vo][sc]",
        "[mus][sc]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=350[duck]",
        "[vo][duck]amix=inputs=2:normalize=0,alimiter=limit=0.95[m]",
    ]
    media.run_ffmpeg(["-i", voice, "-stream_loop", "-1", "-i", music,
                      "-filter_complex", ";".join(chain), "-map", "[m]",
                      "-t", "%.3f" % total, "-c:a", "pcm_s16le", "-y", out], capture=False)


def _loudnorm(src, out, target=-14.0, tp=-1.0, lra=11.0):
    """Two-pass EBU R128 normalisation. Returns the measured input loudness."""
    p = media.run_ffmpeg(["-i", src, "-af",
                          "loudnorm=I=%s:TP=%s:LRA=%s:print_format=json" % (target, tp, lra),
                          "-f", "null", "-"], check=False)
    err = (p.stderr or b"").decode("utf-8", "replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
    if not m:
        media.run_ffmpeg(["-i", src, "-af", "loudnorm=I=%s:TP=%s:LRA=%s" % (target, tp, lra),
                          "-ar", "48000", "-c:a", "pcm_s16le", "-y", out], capture=False)
        return None
    s = json.loads(m.group(0))
    af = ("loudnorm=I=%s:TP=%s:LRA=%s:measured_I=%s:measured_TP=%s:measured_LRA=%s:"
          "measured_thresh=%s:offset=%s:linear=true"
          % (target, tp, lra, s["input_i"], s["input_tp"], s["input_lra"],
             s["input_thresh"], s["target_offset"]))
    media.run_ffmpeg(["-i", src, "-af", af, "-ar", "48000", "-c:a", "pcm_s16le", "-y", out],
                     capture=False)
    return float(s["input_i"])


def measure_lufs(path):
    p = media.run_ffmpeg(["-i", path, "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                         check=False)
    err = (p.stderr or b"").decode("utf-8", "replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
    if not m:
        return None
    s = json.loads(m.group(0))
    return {"lufs": float(s["input_i"]), "true_peak": float(s["input_tp"])}


# ---------------------------------------------------------------------------
# captions — timed from speech, spelled from the script
# ---------------------------------------------------------------------------

def _norm(w):
    return re.sub(r"[^a-z0-9%$]", "", w.lower().replace("’", "").replace("'", ""))


def align_script(script_text, heard_words):
    """Return script tokens with times borrowed from the transcript.

    Caption text always equals the approved script; Whisper only supplies timing.
    Unmatched script words are interpolated between their matched neighbours.
    """
    toks = [t for t in re.findall(r"\S+", script_text or "")]
    if not toks:
        return []
    a = [_norm(t) for t in toks]
    b = [_norm(w["word"]) for w in heard_words]
    times = [None] * len(toks)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            w = heard_words[blk.b + k]
            times[blk.a + k] = (w["start"], w["end"])
    # interpolate the gaps
    known = [i for i, t in enumerate(times) if t]
    if not known:
        return []
    for i in range(len(toks)):
        if times[i]:
            continue
        prev = max([k for k in known if k < i], default=None)
        nxt = min([k for k in known if k > i], default=None)
        if prev is None:
            s = times[nxt][0] - 0.3 * (nxt - i)
        elif nxt is None:
            s = times[prev][1] + 0.3 * (i - prev - 1)
        else:
            span = times[nxt][0] - times[prev][1]
            s = times[prev][1] + span * (i - prev) / float(nxt - prev)
        times[i] = (max(0.0, s), max(0.0, s) + 0.28)
    return [{"word": t, "start": round(s, 3), "end": round(e, 3)}
            for t, (s, e) in zip(toks, times)]


def _cards(words, max_words):
    cards, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or re.search(r"[.!?,;:]$", w["word"]):
            cards.append(cur)
            cur = []
    if cur:
        cards.append(cur)
    return cards


def _ass_time(t):
    t = max(0.0, float(t))
    return "%d:%02d:%05.2f" % (int(t // 3600), int((t % 3600) // 60), t % 60)


def _esc(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")")


def build_captions(timed_words, W, H, style, platform, text_cards=None):
    k = H / 1920.0
    mv = int(SAFE_MARGIN_V.get(platform, 540) * k)
    side = int(64 * k)
    if style == "clean":
        font, size, outline, shadow, per = "Arial", int(62 * k), int(4 * k), 0, 4
        bold = -1
    else:
        font, size, outline, shadow, per = "Arial Black", int(74 * k), int(7 * k), int(3 * k), 3
        bold = 0
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Cap,%s,%d,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,%d,0,0,0,100,100,0,0,1,"
            "%d,%d,2,%d,%d,%d,1\n"
            "Style: Card,Arial Black,%d,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,"
            "100,0,0,1,%d,%d,5,%d,%d,0,1\n\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            % (W, H, font, size, bold, outline, shadow, side, side, mv,
               int(92 * k), int(8 * k), shadow, side, side))
    ev = []
    for card in _cards(timed_words, per):
        c_start = card[0]["start"]
        c_end = max(card[-1]["end"], c_start + 0.35)
        if style == "karaoke":
            for i, w in enumerate(card):
                s = w["start"] if i else c_start
                e = card[i + 1]["start"] if i + 1 < len(card) else c_end
                if e <= s:
                    continue
                parts = []
                for j, x in enumerate(card):
                    txt = _esc(x["word"])
                    parts.append("{\\c%s}%s{\\c&H00FFFFFF&}" % (ACCENT_ASS, txt) if j == i else txt)
                ev.append("Dialogue: 0,%s,%s,Cap,,0,0,0,,%s"
                          % (_ass_time(s), _ass_time(e), " ".join(parts)))
        else:
            ev.append("Dialogue: 0,%s,%s,Cap,,0,0,0,,%s"
                      % (_ass_time(c_start), _ass_time(c_end),
                         " ".join(_esc(x["word"]) for x in card)))
    for c in text_cards or []:
        ev.append("Dialogue: 1,%s,%s,Card,,0,0,0,,%s"
                  % (_ass_time(c["start"]), _ass_time(c["end"]), _esc(c["text"])))
    return head + "\n".join(ev) + "\n"


def _timeline_words(shots, segments, word_source):
    """Map each shot's words (clip time) onto the output timeline, script-spelled."""
    out, cards = [], []
    by_shot = {}
    for s in segments:
        by_shot.setdefault(s["shot"], []).append(s)
    for si, shot in enumerate(shots):
        segs = by_shot.get(si, [])
        if not segs:
            continue
        text = (shot.get("caption") or shot.get("dialogue") or "").strip()
        if not text:
            continue
        speaking = segs[0]["speaking"]
        words = word_source(si, shot) if speaking else []
        timed = align_script(text, words) if words else []
        if not timed:
            # silent shot, or no transcript: spread the caption across the kept picture
            span_start, span_end = segs[0]["at"], segs[-1]["at"] + segs[-1]["dur"]
            toks = text.split()
            step = (span_end - span_start) / max(1, len(toks))
            for i, t in enumerate(toks):
                out.append({"word": t, "start": span_start + i * step,
                            "end": span_start + (i + 1) * step})
            continue
        for w in timed:
            # Whisper often places a word's start a little before the RMS trim point,
            # and words inside a removed pause have no picture. Snap every word into
            # the nearest kept segment — a script word is never allowed to drop.
            def dist(sg):
                if sg["in"] <= w["start"] <= sg["out"]:
                    return 0.0
                return min(abs(w["start"] - sg["in"]), abs(w["start"] - sg["out"]))
            s = min(segs, key=dist)
            local = min(max(w["start"], s["in"]), max(s["in"], s["out"] - 0.12))
            length = max(0.12, w["end"] - w["start"])
            st = s["at"] + (local - s["in"])
            en = min(s["at"] + s["dur"], st + length)
            out.append({"word": w["word"], "start": round(st, 3), "end": round(max(en, st + 0.1), 3)})
    out.sort(key=lambda w: w["start"])
    return out


# ---------------------------------------------------------------------------
# the render
# ---------------------------------------------------------------------------

def render(job_dir, shots, settings, name="ad", log=print, word_source=None):
    """shots: ordered list of {clip_path, dialogue, caption, mute_in_edit, duration}.
    settings: aspect, pacing, transitions, captions, platform, music{mode,mood,bpm,path},
    look, punch_in, jcut, textless."""
    if not shots:
        raise EditError("Nothing to edit — no approved clips.")
    W, H = media.dims_for(settings.get("aspect", "9:16"))
    cut = os.path.join(job_dir, "cut")
    final_dir = os.path.join(job_dir, "final")
    os.makedirs(cut, exist_ok=True)
    os.makedirs(final_dir, exist_ok=True)

    segments, total = plan_cut(shots, settings)
    log("Cut plan: %d segments from %d clips, %.1fs (pacing: %s%s)."
        % (len(segments), len(shots), total, settings.get("pacing", "natural"),
           ", smooth transitions" if settings.get("transitions") == "smooth" else ""))

    vfiles, afiles = [], []
    for i, seg in enumerate(segments):
        v = os.path.join(cut, "seg_%02d.mp4" % i)
        a = os.path.join(cut, "seg_%02d.wav" % i)
        _render_video_seg(seg, W, H, v)
        _render_audio_seg(seg, a)
        vfiles.append(v)
        afiles.append(a)

    picture = os.path.join(cut, "picture.mp4")
    _join_picture(vfiles, segments, picture)

    voice = os.path.join(cut, "voice.wav")
    _mix_voice(afiles, segments, total, voice)
    if any(s["prelap"] for s in segments):
        log("J-cuts on %d clip changes — sound arrives ~%d frames before picture."
            % (sum(1 for s in segments if s["prelap"]), int(PRELAP * FPS)))

    mix = voice
    music_cfg = settings.get("music") or {}
    mode = music_cfg.get("mode", "generated")
    if mode in ("generated", "file") and total > 2:
        if mode == "file" and music_cfg.get("path") and os.path.exists(music_cfg["path"]):
            bed = music_cfg["path"]
        else:
            bed = os.path.join(cut, "music.wav")
            hits = [round(s["at"], 2) for s in segments if s["new_clip"]][:8]
            media.write_wav(bed, media.make_music(total, int(music_cfg.get("bpm", 120)),
                                                  music_cfg.get("mood", "drive"), hits))
        hook_end = segments[0]["dur"] if len(shots) > 1 else 0.0
        last_clip_start = max([s["at"] for s in segments if s["new_clip"]], default=None)
        silence_at = (last_clip_start - 0.5) if (last_clip_start and settings.get("silence_beat", True)
                                                 and last_clip_start > hook_end + 1) else None
        mix = os.path.join(cut, "mix.wav")
        _mix_music(voice, bed, total, hook_end, silence_at, float(music_cfg.get("gain", 0.5)), mix)
        log("Music: enters after the hook at %.1fs%s, ducked under voice."
            % (hook_end, ", silence beat at %.1fs" % silence_at if silence_at else ""))

    norm = os.path.join(cut, "mix_norm.wav")
    measured = _loudnorm(mix, norm)
    log("Loudness normalised to -14 LUFS / -1 dBTP%s."
        % (" (was %.1f LUFS)" % measured if measured is not None else ""))

    # captions
    ass_path = None
    style = settings.get("captions", "karaoke")
    if style != "none":
        src = word_source or (lambda si, shot: [])
        words = _timeline_words(shots, segments, src)
        if words:
            ass_path = os.path.join(cut, "captions.ass")
            with open(ass_path, "w") as f:
                f.write(build_captions(words, W, H, style, settings.get("platform", "tiktok")))
            log("Captions: %d words, %s style, placed in the %s safe zone."
                % (len(words), style, settings.get("platform", "tiktok")))

    look = LOOKS.get(settings.get("look", "phone"))
    outputs = {}
    for variant in (["main"] + (["textless"] if settings.get("textless") else [])):
        vf = []
        if look:
            vf.append(look)
        if ass_path and variant == "main":
            vf.append("ass='%s'" % media.ass_escape(ass_path))
        vf.append("format=yuv420p")
        suffix = "" if variant == "main" else "_textless"
        out = os.path.join(final_dir, "%s%s.mp4" % (name, suffix))
        media.run_ffmpeg(["-i", picture, "-i", norm, "-map", "0:v", "-map", "1:a",
                          "-vf", ",".join(vf), "-c:v", "libx264", "-preset", "medium",
                          "-crf", "18", "-level", "5.1", "-pix_fmt", "yuv420p",
                          "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                          "-movflags", "+faststart", "-shortest", "-y", out], capture=False)
        outputs[variant] = out

    main = outputs["main"]
    info = media.probe(main)
    loud = measure_lufs(main)
    return {"output": main, "outputs": outputs, "duration": info.get("duration"),
            "width": info.get("width"), "height": info.get("height"),
            "has_audio": info.get("has_audio"), "segments": len(segments),
            "loudness": loud, "captions": bool(ass_path)}
