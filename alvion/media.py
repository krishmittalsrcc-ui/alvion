"""Media engine: probing, audio measurement, captions, music, assembly.

Ported from the verified adforge engine — the handle/silence measurement and the
ffmpeg filtergraph here are the ones proven against known ground truth.

There is no ffmpeg on PATH on macOS by default; imageio_ffmpeg ships a full 7.1
build with libass, freetype, fontconfig and harfbuzz enabled.
"""

import argparse
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import wave


class MediaError(RuntimeError):
    """Anything the media engine cannot do. Never SystemExit — this runs inside
    worker threads, where SystemExit is swallowed silently and kills the thread."""

# ----------------------------------------------------------------------------
# ffmpeg plumbing
# ----------------------------------------------------------------------------

def ffmpeg_exe():
    """Resolve the bundled ffmpeg. Never rely on PATH."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise MediaError(
        "No ffmpeg available. Expected imageio_ffmpeg to provide one.\n"
        "  python3 -m pip install --user imageio-ffmpeg"
    )


def run_ffmpeg(args, capture=True, check=True):
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin"] + args
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", "replace")
        tail = "\n".join(tail.strip().splitlines()[-25:])
        raise MediaError("ffmpeg failed (%d):\n%s" % (proc.returncode, tail))
    return proc


def ass_escape(path):
    """Escape a filesystem path for use inside an ffmpeg filtergraph."""
    p = os.path.abspath(path)
    p = p.replace("\\", "\\\\").replace(":", "\\:")
    p = p.replace("'", "\\'").replace("[", "\\[").replace("]", "\\]")
    p = p.replace(",", "\\,").replace(";", "\;")
    return p


# ----------------------------------------------------------------------------
# probing
# ----------------------------------------------------------------------------

_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")
_VID_RE = re.compile(r"Stream #\d+:\d+.*?: Video: .*?(\d{2,5})x(\d{2,5})")
_AUD_RE = re.compile(r"Stream #\d+:\d+.*?: Audio: (\w+).*?(\d+) Hz")


def probe(path):
    """Container facts. Tries PyAV, falls back to parsing ffmpeg stderr."""
    info = {
        "path": path, "duration": None, "width": None, "height": None,
        "fps": None, "has_audio": False, "audio_rate": None, "audio_codec": None,
    }
    try:
        import av
        with av.open(path) as c:
            if c.duration:
                info["duration"] = round(c.duration / av.time_base, 3)
            for s in c.streams:
                if s.type == "video" and info["width"] is None:
                    info["width"] = s.codec_context.width
                    info["height"] = s.codec_context.height
                    try:
                        info["fps"] = round(float(s.average_rate), 3)
                    except Exception:
                        info["fps"] = None
                    if info["duration"] is None and s.duration and s.time_base:
                        info["duration"] = round(float(s.duration * s.time_base), 3)
                elif s.type == "audio":
                    info["has_audio"] = True
                    info["audio_rate"] = s.codec_context.sample_rate
                    info["audio_codec"] = s.codec_context.name
        if info["duration"] is not None:
            return info
    except Exception:
        pass

    proc = run_ffmpeg(["-i", path], check=False)
    err = (proc.stderr or b"").decode("utf-8", "replace")
    m = _DUR_RE.search(err)
    if m:
        info["duration"] = round(
            int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 3)
    m = _VID_RE.search(err)
    if m:
        info["width"], info["height"] = int(m.group(1)), int(m.group(2))
    m = _AUD_RE.search(err)
    if m:
        info["has_audio"] = True
        info["audio_codec"], info["audio_rate"] = m.group(1), int(m.group(2))
    return info


def decode_pcm(path, rate=16000):
    """Decode to mono float32 in [-1, 1]. Returns (samples, rate)."""
    import numpy as np
    proc = run_ffmpeg([
        "-i", path, "-vn", "-ac", "1", "-ar", str(rate),
        "-f", "s16le", "-acodec", "pcm_s16le", "-",
    ])
    raw = proc.stdout or b""
    if not raw:
        return np.zeros(0, dtype="float32"), rate
    arr = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    return arr, rate


def rms_db(samples, rate, win_ms):
    """RMS per window, in dBFS. Returns (db_array, window_seconds)."""
    import numpy as np
    win = max(1, int(rate * win_ms / 1000.0))
    n = len(samples) // win
    if n == 0:
        return np.zeros(0, dtype="float32"), win / float(rate)
    trimmed = samples[:n * win].reshape(n, win)
    rms = np.sqrt(np.mean(trimmed * trimmed, axis=1)) + 1e-9
    return 20.0 * np.log10(rms), win / float(rate)


def speech_threshold(db):
    """max(noise_floor + 10dB, p85 - 18dB) — the documented house threshold."""
    import numpy as np
    if len(db) == 0:
        return -60.0
    floor = float(np.percentile(db, 10))
    p85 = float(np.percentile(db, 85))
    return max(floor + 10.0, p85 - 18.0)


# ----------------------------------------------------------------------------
# handles — head/tail silence on a generated clip
# ----------------------------------------------------------------------------

def measure_handles(path, win_ms=50, pass_at=0.6):
    import numpy as np
    info = probe(path)
    if not info["has_audio"]:
        return {"path": path, "error": "no audio stream", "duration": info["duration"]}
    samples, rate = decode_pcm(path)
    db, wsec = rms_db(samples, rate, win_ms)
    if len(db) == 0:
        return {"path": path, "error": "no decodable audio"}
    thr = speech_threshold(db)
    loud = np.where(db > thr)[0]
    dur = len(samples) / float(rate)
    if len(loud) == 0:
        return {"path": path, "duration": round(dur, 2), "speech": False,
                "head": None, "tail": None, "pass": False}
    head = float(loud[0] * wsec)
    tail = float(dur - (loud[-1] + 1) * wsec)
    return {
        "path": path,
        "duration": round(dur, 2),
        "speech": True,
        "threshold_db": round(thr, 1),
        "head": round(head, 2),
        "tail": round(max(0.0, tail), 2),
        "pass": head >= pass_at and tail >= pass_at,
    }


# ----------------------------------------------------------------------------
# silence / pause map
# ----------------------------------------------------------------------------

def speech_segments(path, win_ms=25, fill_gap_ms=120, min_speech_ms=120):
    """Contiguous speech spans, with sub-120ms gaps filled so words don't split."""
    import numpy as np
    samples, rate = decode_pcm(path)
    db, wsec = rms_db(samples, rate, win_ms)
    if len(db) == 0:
        return [], 0.0
    thr = speech_threshold(db)
    voiced = db > thr

    segs = []
    start = None
    for i, v in enumerate(voiced):
        if v and start is None:
            start = i
        elif not v and start is not None:
            segs.append([start * wsec, i * wsec])
            start = None
    if start is not None:
        segs.append([start * wsec, len(voiced) * wsec])

    fill = fill_gap_ms / 1000.0
    merged = []
    for s in segs:
        if merged and s[0] - merged[-1][1] < fill:
            merged[-1][1] = s[1]
        else:
            merged.append(s)

    min_s = min_speech_ms / 1000.0
    merged = [s for s in merged if (s[1] - s[0]) >= min_s]
    return [(round(a, 3), round(b, 3)) for a, b in merged], len(samples) / float(rate)


# ----------------------------------------------------------------------------
# transcription (faster-whisper)
# ----------------------------------------------------------------------------

def transcribe(path, model_size="base", language=None):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        path, word_timestamps=True, language=language, vad_filter=True)
    out = {"language": info.language, "duration": info.duration, "words": [], "segments": []}
    for seg in segments:
        out["segments"].append(
            {"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip()})
        for w in (seg.words or []):
            out["words"].append(
                {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()})
    return out


# ----------------------------------------------------------------------------
# frame extraction
# ----------------------------------------------------------------------------

def extract_frame(path, at, out_path):
    """Pull one frame. -copyts because -ss before -i resets timestamps to 0."""
    info = probe(path)
    if isinstance(at, str) and at.endswith("%"):
        frac = float(at[:-1]) / 100.0
        at = (info["duration"] or 0) * frac
    at = float(at)
    run_ffmpeg(["-ss", "%.3f" % at, "-copyts", "-i", path,
                "-frames:v", "1", "-q:v", "2", "-y", out_path], capture=False)
    return out_path


# ----------------------------------------------------------------------------
# captions — ASS in the house style
# ----------------------------------------------------------------------------

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial Black,{cap_size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,{cap_out},{cap_sh},2,{mh},{mh},{cap_mv},1
Style: Card,Arial Black,{card_size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,{card_out},{cap_sh},5,{mh},{mh},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_time(t):
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return "%d:%02d:%05.2f" % (h, m, s)


def build_ass(cues, width=1080, height=1920, cards=None):
    """cues/cards: [{start, end, text}]. Card style is centred and larger."""
    k = height / 1920.0
    head = ASS_HEADER.format(
        w=width, h=height,
        cap_size=int(round(74 * k)), cap_out=int(round(7 * k)),
        cap_sh=int(round(4 * k)), cap_mv=int(round(360 * k)),
        card_size=int(round(96 * k)), card_out=int(round(8 * k)),
        mh=int(round(60 * k)),
    )
    lines = []
    for c in cues or []:
        txt = str(c["text"]).strip().replace("\n", "\\N")
        lines.append("Dialogue: 0,%s,%s,Caption,,0,0,0,,%s"
                     % (ass_time(c["start"]), ass_time(c["end"]), txt))
    for c in cards or []:
        txt = str(c["text"]).strip().replace("\n", "\\N")
        lines.append("Dialogue: 1,%s,%s,Card,,0,0,0,,%s"
                     % (ass_time(c["start"]), ass_time(c["end"]), txt))
    return head + "\n".join(lines) + "\n"


_CLAUSE_RE = re.compile(r"[^.!?\n]+[.!?]*")


def split_clauses(text, max_words=5):
    """Sentences first, then split long ones at commas, then hard-wrap."""
    raw = []
    for chunk in _CLAUSE_RE.findall(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk.split()) <= max_words:
            raw.append(chunk)
            continue
        parts = [p.strip() for p in re.split(r"(?<=[,;:])\s+", chunk) if p.strip()]
        for p in parts:
            words = p.split()
            if len(words) <= max_words:
                raw.append(p)
            else:
                for i in range(0, len(words), max_words):
                    raw.append(" ".join(words[i:i + max_words]))
    return raw


def speech_time_to_real(offset, segs):
    """Map a cumulative-speech-time offset back onto the real timeline."""
    acc = 0.0
    for a, b in segs:
        span = b - a
        if offset <= acc + span:
            return a + (offset - acc)
        acc += span
    return segs[-1][1] if segs else 0.0


def cues_from_audio_and_script(audio, script_text, max_words=5):
    """Allocate clauses across measured speech time, proportional to word count."""
    segs, _dur = speech_segments(audio)
    if not segs:
        raise MediaError("No speech detected in %s" % audio)
    clauses = split_clauses(script_text, max_words=max_words)
    if not clauses:
        raise MediaError("Script produced no clauses")

    total_speech = sum(b - a for a, b in segs)
    weights = [max(1, len(c.split())) for c in clauses]
    total_w = float(sum(weights))

    cues, acc = [], 0.0
    for clause, w in zip(clauses, weights):
        span = total_speech * (w / total_w)
        start = speech_time_to_real(acc, segs)
        end = speech_time_to_real(min(total_speech, acc + span), segs)
        if end <= start:
            end = start + 0.4
        cues.append({"start": round(start, 3), "end": round(end, 3), "text": clause})
        acc += span
    return cues, segs


# ----------------------------------------------------------------------------
# music bed — synthesised, royalty free, arranged to the cut
# ----------------------------------------------------------------------------

MOODS = {
    "drive":  {"root": 55.0,  "prog": [0, 8, 3, 10], "minor": True,  "kick": True,  "bright": 0.55},
    "warm":   {"root": 65.41, "prog": [0, 7, 9, 5],  "minor": False, "kick": False, "bright": 0.35},
    "tense":  {"root": 49.0,  "prog": [0, 0, 1, 0],  "minor": True,  "kick": True,  "bright": 0.25},
    "uplift": {"root": 65.41, "prog": [9, 5, 0, 7],  "minor": False, "kick": True,  "bright": 0.7},
}


def _adsr(n, sr, a=0.01, d=0.1, s=0.7, r=0.2):
    import numpy as np
    env = np.ones(n, dtype="float32")
    ai, di = int(a * sr), int(d * sr)
    ri = int(r * sr)
    if ai > 0:
        env[:ai] = np.linspace(0, 1, ai, dtype="float32")
    if di > 0:
        env[ai:ai + di] = np.linspace(1, s, min(di, max(0, n - ai)), dtype="float32")
    env[ai + di:] = s
    if ri > 0 and ri < n:
        env[-ri:] *= np.linspace(1, 0, ri, dtype="float32")
    return env


def _tone(freq, dur, sr, kind="saw", detune=0.0):
    import numpy as np
    n = max(1, int(dur * sr))
    t = np.arange(n, dtype="float32") / sr
    if kind == "sine":
        return np.sin(2 * np.pi * freq * t).astype("float32")
    out = np.zeros(n, dtype="float32")
    for mult in (1.0, 1.0 + detune, 1.0 - detune):
        ph = (freq * mult * t) % 1.0
        out += (2.0 * ph - 1.0).astype("float32")
    return out / 3.0


_PAD_CACHE = {}


def _pad_voice(freq, dur, sr, cutoff):
    """Filtered, enveloped pad note. Cached: the per-sample filter is the
    slowest thing here and a bar's chord voices repeat throughout the track."""
    key = (round(freq, 3), round(dur, 4), sr, round(cutoff, 1))
    if key not in _PAD_CACHE:
        sig = _tone(freq, dur, sr, "saw", 0.008)
        sig = _lowpass(sig, sr, cutoff)
        sig = sig * _adsr(len(sig), sr, 0.25, 0.4, 0.75, 0.5) * 0.11
        _PAD_CACHE[key] = sig
    return _PAD_CACHE[key]


def _lowpass(x, sr, cutoff):
    import numpy as np
    dt = 1.0 / sr
    rc = 1.0 / (2 * np.pi * max(20.0, cutoff))
    alpha = dt / (rc + dt)
    out = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += alpha * (x[i] - acc)
        out[i] = acc
    return out


def make_music(duration, bpm=120, mood="drive", hits=None, sr=44100, seed=7):
    import numpy as np
    rng = np.random.default_rng(seed)
    cfg = MOODS.get(mood, MOODS["drive"])
    n = int(duration * sr)
    left = np.zeros(n, dtype="float32")
    right = np.zeros(n, dtype="float32")

    beat = 60.0 / bpm
    bar = beat * 4
    third = 3 if cfg["minor"] else 4

    def add(buf, sig, at):
        i = int(at * sr)
        if i >= n:
            return
        seg = sig[:max(0, min(len(sig), n - i))]
        buf[i:i + len(seg)] += seg

    bar_i = 0
    t = 0.0
    while t < duration:
        semis = cfg["prog"][bar_i % len(cfg["prog"])]
        root = cfg["root"] * (2 ** (semis / 12.0))

        # bass: root on beats 1 and 3
        for b in (0, 2):
            sig = _tone(root, beat * 0.9, sr, "saw", 0.004)
            sig *= _adsr(len(sig), sr, 0.005, 0.08, 0.6, 0.12) * 0.32
            add(left, sig, t + b * beat)
            add(right, sig, t + b * beat)

        # pad: root / third / fifth across the bar, stereo spread
        for idx, iv in enumerate((0, third, 7)):
            f = root * 4 * (2 ** (iv / 12.0))
            sig = _pad_voice(f, bar, sr, 500 + 2200 * cfg["bright"])
            pan = (idx - 1) * 0.35
            add(left, sig * (1.0 - max(0.0, pan)), t)
            add(right, sig * (1.0 + min(0.0, pan)), t)

        # pluck on the offbeats
        for b in (1.5, 3.5):
            f = root * 8 * (2 ** (third / 12.0))
            sig = _tone(f, beat * 0.4, sr, "sine")
            sig *= _adsr(len(sig), sr, 0.002, 0.06, 0.25, 0.15) * 0.14 * cfg["bright"]
            add(left, sig, t + b * beat)
            add(right, sig * 0.85, t + b * beat)

        # drums
        for b in range(4):
            if cfg["kick"]:
                kn = int(0.12 * sr)
                kt = np.arange(kn, dtype="float32") / sr
                kf = 110 * np.exp(-kt * 28) + 45
                k = np.sin(2 * np.pi * kf * kt).astype("float32")
                k *= np.exp(-kt * 16) * 0.5
                add(left, k, t + b * beat)
                add(right, k, t + b * beat)
            hn = int(0.05 * sr)
            h = rng.standard_normal(hn).astype("float32")
            h *= np.exp(-np.arange(hn, dtype="float32") / sr * 90) * 0.055 * cfg["bright"]
            add(left, h, t + (b + 0.5) * beat)
            add(right, h * 0.9, t + (b + 0.5) * beat)

        t += bar
        bar_i += 1

    # accents on the edit's cut points
    for h in (hits or []):
        sn = int(0.9 * sr)
        st = np.arange(sn, dtype="float32") / sr
        swell = rng.standard_normal(sn).astype("float32") * np.linspace(0, 1, sn) ** 3
        swell = _lowpass(swell, sr, 6000) * 0.3
        start = max(0.0, float(h) - 0.9)
        add(left, swell, start)
        add(right, swell, start)

    stereo = np.stack([left, right], axis=1)
    stereo = np.tanh(stereo * 1.4)  # soft clip
    peak = float(np.max(np.abs(stereo))) or 1.0
    stereo = stereo / peak * 0.85
    return (stereo * 32767).astype("<i2")


def write_wav(path, pcm16, sr=44100):
    with wave.open(path, "wb") as w:
        w.setnchannels(pcm16.shape[1] if pcm16.ndim > 1 else 1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm16.tobytes())
    return path




# ----------------------------------------------------------------------------
# assembly — takes a plain dict spec (no YAML file needed)
# ----------------------------------------------------------------------------

def assemble(spec, base_dir, dry_run=False):
    """Build the cut.

    spec = {
      output, width, height, fps,
      captions: <path or None>,
      music: {path, gain, duck},
      segments: [{clip, in, out, mute}]
    }
    Relative paths resolve against base_dir.
    """
    def rel(p):
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(base_dir, p))

    W = int(spec.get("width", 1080))
    H = int(spec.get("height", 1920))
    FPS = int(spec.get("fps", 30))
    segs = spec.get("segments") or []
    if not segs:
        raise ValueError("No segments to assemble")

    out_path = rel(spec.get("output", "output.mp4"))
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    inputs, vparts, aparts, total = [], [], [], 0.0
    for i, seg in enumerate(segs):
        src = rel(seg["clip"])
        if not os.path.exists(src):
            raise ValueError("Missing clip: %s" % src)
        info = probe(src)
        t_in = float(seg.get("in", 0.0))
        t_out = float(seg.get("out") or info["duration"] or 0.0)
        if t_out <= t_in:
            raise ValueError("Segment %d: out (%s) must exceed in (%s)" % (i, t_out, t_in))
        dur = t_out - t_in
        total += dur
        inputs += ["-i", src]

        vparts.append(
            "[%d:v]trim=start=%.4f:end=%.4f,setpts=PTS-STARTPTS,"
            "scale=%d:%d:force_original_aspect_ratio=decrease,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=%d[v%d]"
            % (i, t_in, t_out, W, H, W, H, FPS, i))

        if info["has_audio"] and not seg.get("mute", False):
            aparts.append(
                "[%d:a]atrim=start=%.4f:end=%.4f,asetpts=PTS-STARTPTS,"
                "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a%d]"
                % (i, t_in, t_out, i))
        else:
            aparts.append(
                "anullsrc=r=48000:cl=stereo,atrim=duration=%.4f,asetpts=PTS-STARTPTS[a%d]"
                % (dur, i))

    chain = vparts + aparts
    concat_in = "".join("[v%d][a%d]" % (i, i) for i in range(len(segs)))
    chain.append("%sconcat=n=%d:v=1:a=1[vc][ac]" % (concat_in, len(segs)))

    ass_file = spec.get("captions")
    if ass_file and os.path.exists(rel(ass_file)):
        chain.append("[vc]ass='%s'[vout]" % ass_escape(rel(ass_file)))
        vlabel = "[vout]"
    else:
        vlabel = "[vc]"

    music = spec.get("music") or {}
    mpath = music.get("path")
    if mpath and os.path.exists(rel(mpath)):
        gain = float(music.get("gain", 0.55))
        midx = len(segs)
        inputs += ["-stream_loop", "-1", "-i", rel(mpath)]
        chain.append(
            "[%d:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            "atrim=duration=%.4f,asetpts=PTS-STARTPTS,volume=%.3f[mus]" % (midx, total, gain))
        if music.get("duck", True):
            chain.append("[ac]asplit=2[ac1][ac2]")
            chain.append("[mus][ac1]sidechaincompress=threshold=0.03:ratio=8:"
                         "attack=20:release=400[duck]")
            chain.append("[duck][ac2]amix=inputs=2:normalize=0,alimiter=limit=0.95[aout]")
        else:
            chain.append("[mus][ac]amix=inputs=2:normalize=0,alimiter=limit=0.95[aout]")
    else:
        chain.append("[ac]alimiter=limit=0.95[aout]")

    filtergraph = ";".join(chain)
    args = inputs + [
        "-filter_complex", filtergraph,
        "-map", vlabel, "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-level", "5.1", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-y", out_path,
    ]
    if dry_run:
        return {"output": out_path, "duration": total, "filtergraph": filtergraph}

    run_ffmpeg(args, capture=False)
    return {"output": out_path, "duration": total}


def still_to_video(image_path, out_path, duration, with_tone=False):
    """Ken-Burns-free still -> clip. Used by the mock provider."""
    args = ["-loop", "1", "-t", "%.3f" % duration, "-i", image_path]
    if with_tone:
        # Speech-shaped: ~0.8s silent handle, tone, ~0.8s silent handle — so the
        # handle measurement downstream has something real to measure.
        head, tail = 0.8, min(0.9, duration * 0.2)
        args += ["-f", "lavfi", "-i",
                 "sine=frequency=220:duration=%.3f:sample_rate=48000" % duration,
                 "-filter_complex",
                 "[1:a]volume='if(between(t,%.3f,%.3f),0.8,0)':eval=frame,"
                 "aformat=channel_layouts=stereo[aud]" % (head, duration - tail)]
    else:
        args += ["-f", "lavfi", "-i",
                 "anullsrc=r=48000:cl=stereo:d=%.3f" % duration]
    if with_tone:
        args += ["-map", "0:v", "-map", "[aud]"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-r", "30", "-c:a", "aac", "-shortest", "-y", out_path]
    run_ffmpeg(args, capture=False)
    return out_path


ASPECT_DIMS = {"9:16": (1080, 1920), "16:9": (1920, 1080),
               "1:1": (1080, 1080), "4:5": (1080, 1350)}


def dims_for(aspect_ratio):
    return ASPECT_DIMS.get(aspect_ratio, (1080, 1920))
