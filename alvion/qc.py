"""Automated clip QC — the checks Krish kept doing by eye, done by measurement.

Each check targets a rejection that recurred across real client jobs:
  background drift   "the background is changing" — the single most common note
  script diff        "don't change a single word" — dropped, added or repeated words
  handles            "very hard cut" — dialogue that ends on the last frame
  audio / format     silent dialogue clips, wrong aspect ratio from the model

QC never approves anything. It flags, so the human review is faster and nothing
obvious slips through. A clean QC is not a pass; a flag is a reason to look.
"""
import re

from . import media

# Border-strip mean pixel difference vs the first frame, 0–255 scale.
# Measured on real jobs: a stable room scored 2.6–11.4, visibly drifting rooms 16–21.
DRIFT_WARN = 12.0
DRIFT_FAIL = 16.0

_WHISPER = None


def _frames_gray(path, times, w=144, h=256):
    """Decode small grayscale frames at the given times. Returns list of numpy arrays."""
    import numpy as np
    out = []
    for t in times:
        proc = media.run_ffmpeg([
            "-ss", "%.3f" % max(0.0, t), "-i", path, "-frames:v", "1",
            "-vf", "scale=%d:%d:force_original_aspect_ratio=disable,format=gray" % (w, h),
            "-f", "rawvideo", "-"], check=False)
        raw = proc.stdout or b""
        if len(raw) >= w * h:
            out.append(np.frombuffer(raw[:w * h], dtype="uint8").reshape(h, w).astype("float32"))
    return out


def edge_drift(path, border=0.12):
    """How much the frame edges (where the room lives) change across the clip.

    The subject usually occupies the centre and is supposed to move; the edges are
    walls, furniture and set. If they change, the background is morphing.
    """
    import numpy as np
    info = media.probe(path)
    dur = info.get("duration") or 0
    if dur <= 0.5:
        return {"score": None, "note": "too short to measure"}
    times = [0.1] + [dur * f for f in (0.25, 0.5, 0.75)] + [max(0.1, dur - 0.15)]
    frames = _frames_gray(path, times)
    if len(frames) < 3:
        return {"score": None, "note": "could not decode frames"}
    h, w = frames[0].shape
    bh, bw = max(2, int(h * border)), max(2, int(w * border))
    mask = np.zeros((h, w), dtype=bool)
    mask[:bh, :] = mask[-bh:, :] = True
    mask[:, :bw] = mask[:, -bw:] = True
    ref = frames[0][mask]
    diffs = [float(np.mean(np.abs(f[mask] - ref))) for f in frames[1:]]
    worst = max(diffs)
    return {"score": round(worst, 1), "per_sample": [round(d, 1) for d in diffs]}


def _norm_words(text):
    text = (text or "").lower()
    text = re.sub(r"[‘’']", "", text)
    text = re.sub(r"[^a-z0-9%$ ]+", " ", text)
    return [w for w in text.split() if w]


def transcribe_words(path, model_size="base.en"):
    """Word-level transcript via faster-whisper (cached locally, runs on CPU)."""
    global _WHISPER
    from faster_whisper import WhisperModel
    if _WHISPER is None or _WHISPER[0] != model_size:
        _WHISPER = (model_size, WhisperModel(model_size, device="cpu", compute_type="int8"))
    model = _WHISPER[1]
    segments, _info = model.transcribe(path, word_timestamps=True, vad_filter=True,
                                       language="en" if model_size.endswith(".en") else None)
    words = []
    for seg in segments:
        for w in (seg.words or []):
            words.append({"start": round(w.start, 3), "end": round(w.end, 3),
                          "word": w.word.strip()})
    return words


def script_diff(path, expected):
    """Compare what was actually said with the approved line."""
    import difflib
    exp = _norm_words(expected)
    if not exp:
        return {"checked": False, "note": "no dialogue expected"}
    try:
        words = transcribe_words(path)
    except Exception as e:
        return {"checked": False, "note": "transcription unavailable: %s" % e}
    got = _norm_words(" ".join(w["word"] for w in words))
    sm = difflib.SequenceMatcher(a=exp, b=got, autojunk=False)
    missing, extra = [], []
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op in ("delete", "replace"):
            missing.extend(exp[a1:a2])
        if op in ("insert", "replace"):
            extra.extend(got[b1:b2])
    return {
        "checked": True,
        "match": round(sm.ratio(), 3),
        "heard": " ".join(w["word"] for w in words),
        "missing": missing[:20],
        "extra": extra[:20],
        "words": words,
    }


def qc_clip(path, shot, aspect="9:16"):
    """Run every check on one generated clip. Returns metrics and human-readable flags."""
    flags, metrics = [], {}
    info = media.probe(path)
    metrics["duration"] = info.get("duration")
    metrics["size"] = "%sx%s" % (info.get("width"), info.get("height"))

    # --- format -----------------------------------------------------------
    W, H = media.dims_for(aspect)
    if info.get("width") and info.get("height"):
        want_portrait = H > W
        got_portrait = info["height"] > info["width"]
        if want_portrait != got_portrait and W != H:
            flags.append({"level": "fail", "code": "aspect",
                          "text": "Came back %s but the ad is %s." % (metrics["size"], aspect)})

    dialogue = (shot.get("dialogue") or "").strip()
    speaking = bool(dialogue) and not shot.get("mute_in_edit")

    # --- audio + handles --------------------------------------------------
    if speaking:
        if not info.get("has_audio"):
            flags.append({"level": "fail", "code": "no_audio",
                          "text": "Dialogue clip has no audio track."})
        else:
            h = media.measure_handles(path)
            metrics["head"], metrics["tail"] = h.get("head"), h.get("tail")
            if not h.get("speech"):
                flags.append({"level": "fail", "code": "no_speech",
                              "text": "No speech detected in a dialogue clip."})
            elif (h.get("tail") or 0) < 0.4:
                flags.append({"level": "warn", "code": "hard_cut",
                              "text": "Ends %.2fs after the last word — a hard cut. Regenerate 1–2s longer."
                                      % (h.get("tail") or 0)})
            elif (h.get("head") or 0) > 1.6:
                flags.append({"level": "warn", "code": "slow_start",
                              "text": "Speech starts %.1fs in — slow opening." % h["head"]})

    # --- background drift -------------------------------------------------
    d = edge_drift(path)
    metrics["drift"] = d.get("score")
    if d.get("score") is not None:
        if d["score"] >= DRIFT_FAIL:
            flags.append({"level": "fail", "code": "drift",
                          "text": "Background changes during the clip (edge drift %.1f)." % d["score"]})
        elif d["score"] >= DRIFT_WARN:
            flags.append({"level": "warn", "code": "drift",
                          "text": "Some background movement (edge drift %.1f) — check the room holds."
                                  % d["score"]})

    # --- script -----------------------------------------------------------
    if speaking and info.get("has_audio"):
        sd = script_diff(path, dialogue)
        if sd.get("checked"):
            metrics["script_match"] = sd["match"]
            metrics["heard"] = sd["heard"]
            if sd["missing"]:
                flags.append({"level": "fail", "code": "words_missing",
                              "text": "Words not heard: “%s”." % " ".join(sd["missing"])})
            if sd["extra"]:
                flags.append({"level": "warn", "code": "words_extra",
                              "text": "Words added or repeated: “%s”." % " ".join(sd["extra"])})
        else:
            metrics["script_note"] = sd.get("note")

    verdict = ("fail" if any(f["level"] == "fail" for f in flags)
               else "warn" if flags else "clean")
    return {"verdict": verdict, "flags": flags, "metrics": metrics,
            "note": "Automated checks only. Watch it: voice, lip sync and hands need eyes."}
