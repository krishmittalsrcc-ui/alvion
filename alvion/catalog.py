"""The model catalogue — Higgsfield models ALVION can drive, with their real options.

Parameters and aspect ratios come from Higgsfield's own `models_explore` catalogue.
Prices are Higgsfield's own `get_cost` preflight quotes (Sept 19 2026, 9:16), stored
per second (video) or per image. When Higgsfield is connected, ALVION re-quotes every
shot live before you approve — these numbers are for choosing, not for billing.

`strengths` are what ALVION's router matches against. They come from Krish's
production results and published 2026 comparisons (see docs/knowledge-sources.md).
"""

import math

VIDEO = {
    "kling3_0": {
        "name": "Kling 3.0", "provider": "Kling", "badge": "K",
        "blurb": "Most natural people. Per-phoneme lip sync, best value.",
        "best_for": ["talking", "avatar", "ugc", "human_motion"],
        "strengths": {"talking": 10, "lip_sync": 10, "human_motion": 9, "value": 9, "product": 6, "realism": 8,
                      "cinematic": 7, "motion": 7, "broll": 6},
        "durations": {"min": 3, "max": 15},
        "resolutions": {"720p": {"mode": "std"}, "1080p": {"mode": "pro"}, "4k": {"mode": "4k"}},
        "audio": {"param": "sound", "on": "on", "off": "off"},
        "frames": {"start": "start_image", "end": "end_image"},
        "aspects": ["9:16", "16:9", "1:1"],
        "price": {"720p": {"sound": 2.0, "silent": 1.5}, "1080p": {"sound": 2.5, "silent": 1.75}},
        "watch": "Keep dialogue clips under ~8s or identity drifts; negate clip-on mics.",
    },
    "kling3_0_turbo": {
        "name": "Kling 3.0 Turbo", "provider": "Kling", "badge": "K",
        "blurb": "Fast, cheap silent animation from one start frame.",
        "best_for": ["broll", "draft"],
        "strengths": {"broll": 7, "value": 9, "human_motion": 7, "talking": 2},
        "durations": {"min": 3, "max": 15},
        "resolutions": {"720p": {"resolution": "720p"}, "1080p": {"resolution": "1080p"}},
        "audio": None,
        "frames": {"start": "start_image"},
        "aspects": ["9:16", "16:9", "1:1"],
        "price": {"720p": {"silent": 1.6}, "1080p": {"silent": 2.0}},
        "watch": "No audio and no end frame.",
    },
    "seedance_2_5": {
        "name": "Seedance 2.5", "provider": "ByteDance", "badge": "S",
        "blurb": "Best at your references — product in hand, identity, up to 30s.",
        "best_for": ["broll", "product", "motion", "references"],
        "strengths": {"product": 10, "references": 10, "motion": 9, "broll": 9, "cinematic": 8, "realism": 8,
                      "talking": 7, "lip_sync": 7, "human_motion": 8, "value": 3},
        "durations": {"min": 4, "max": 30},
        "resolutions": {"720p": {"resolution": "720p"}, "1080p": {"resolution": "1080p"}},
        "audio": {"param": "generate_audio", "on": True, "off": False},
        "frames": {"start": "start_image", "end": "end_image"},
        "fixed": {"mode": "omni_reference", "bitrate_mode": "high"},
        "aspects": ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"],
        "price": {"720p": {"sound": 7.0, "silent": 7.0}, "1080p": {"sound": 12.0, "silent": 12.0}},
        "watch": "Ad-libs if the clip is longer than the line — size to ~2.5 words/sec.",
    },
    "seedance1_5": {
        "name": "Seedance 1.5 Pro", "provider": "ByteDance", "badge": "S",
        "blurb": "Reliable motion at a quarter of Seedance 2.5's price.",
        "best_for": ["broll", "motion"],
        "strengths": {"motion": 8, "broll": 8, "product": 7, "references": 6, "value": 7, "talking": 5},
        "durations": {"options": [4, 8, 12]},
        "resolutions": {"720p": {"resolution": "720p"}, "1080p": {"resolution": "1080p"}},
        "audio": {"param": "generate_audio", "on": True, "off": False},
        "frames": {"start": "start_image", "end": "end_image"},
        "aspects": ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"],
        "price": {"720p": {"sound": 2.0, "silent": 2.0}, "1080p": {"sound": 3.0, "silent": 3.0}},
        "watch": "Durations are fixed at 4, 8 or 12 seconds.",
    },
    "veo3_1": {
        "name": "Veo 3.1", "provider": "Google", "badge": "V",
        "blurb": "Ultra-realistic with native speech. Premium polish.",
        "best_for": ["cinematic", "talking", "realism"],
        "strengths": {"cinematic": 10, "realism": 10, "talking": 8, "lip_sync": 9, "product": 8,
                      "broll": 8, "human_motion": 8, "value": 4},
        "durations": {"options": [4, 6, 8]},
        "resolutions": {"720p": {"quality": "basic", "variant": "veo-3-1-fast"},
                        "1080p": {"quality": "high", "variant": "veo-3-1-fast"}},
        "audio": None, "native_audio": True,
        "frames": {"start": "start_image"},
        "aspects": ["9:16", "16:9"],
        "price": {"720p": {"sound": 2.75}, "1080p": {"sound": 5.0}},
        "watch": "Clips are 4, 6 or 8 seconds; no end frame.",
    },
    "veo3_1_lite": {
        "name": "Veo 3.1 Lite", "provider": "Google", "badge": "V",
        "blurb": "Cheapest credible realism — ideal for B-roll batches.",
        "best_for": ["broll", "draft"],
        "strengths": {"broll": 8, "value": 10, "cinematic": 7, "realism": 7, "talking": 5},
        "durations": {"options": [4, 6, 8]},
        "resolutions": {"720p": {}},
        "audio": {"param": "generate_audio", "on": True, "off": False},
        "frames": {"start": "start_image", "end": "end_image"},
        "aspects": ["9:16", "16:9"],
        "price": {"720p": {"sound": 1.5, "silent": 1.0}},
        "watch": "720p only.",
    },
    "gemini_omni_flash_1_1": {
        "name": "Gemini Omni Flash 1.1", "provider": "Google", "badge": "G",
        "blurb": "Top-ranked audio-video model. Fast B-roll with ambience.",
        "best_for": ["broll", "cinematic"],
        "strengths": {"broll": 9, "cinematic": 8, "realism": 8, "value": 7, "product": 7, "talking": 6},
        "durations": {"min": 3, "max": 10},
        "resolutions": {"720p": {"resolution": "720p"}, "1080p": {"resolution": "1080p"}, "4k": {"resolution": "4k"}},
        "audio": None, "native_audio": True,
        "frames": {"start": "start_image", "end": "end_image"},
        "fixed": {"mode": "image-to-video"},
        "aspects": ["9:16", "16:9"],
        "price": {"720p": {"sound": 3.0}, "1080p": {"sound": 4.5}},
        "watch": "Always generates audio — mute it in the edit. Objects can vanish mid-shot.",
    },
    "minimax_hailuo": {
        "name": "Hailuo 2.3", "provider": "MiniMax", "badge": "H",
        "blurb": "Natural physics and facial emotion. Very affordable.",
        "best_for": ["motion", "emotion", "draft"],
        "strengths": {"motion": 8, "emotion": 9, "human_motion": 8, "value": 10, "broll": 7, "talking": 4},
        "durations": {"options": [6, 10]},
        "resolutions": {"720p": {"resolution": "768", "variant": "minimax-2.3"},
                        "1080p": {"resolution": "1080", "variant": "minimax-2.3"}},
        "audio": None,
        "frames": {"start": "start_image", "end": "end_image"},
        "aspects": ["9:16", "16:9", "1:1"],
        "price": {"720p": {"silent": 1.2}, "1080p": {"silent": 1.67}},
        "watch": "Silent; 6 or 10 seconds only.",
    },
    "wan3_0": {
        "name": "Wan 3.0", "provider": "Wan", "badge": "W",
        "blurb": "Native audio, first/last frame, reasoning mode for hard prompts.",
        "best_for": ["motion", "references"],
        "strengths": {"motion": 8, "references": 8, "talking": 6, "broll": 7, "value": 6},
        "durations": {"min": 2, "max": 30},
        "resolutions": {"720p": {"resolution": "720p"}, "1080p": {"resolution": "1080p"}},
        "audio": {"param": "generate_audio", "on": True, "off": False},
        "frames": {"start": "start_image", "end": "end_image"},
        "aspects": ["9:16", "16:9", "1:1", "4:3", "3:4"],
        "price": {"720p": {"sound": 2.5, "silent": 2.5}, "1080p": {"sound": 3.5, "silent": 3.5}},
        "watch": "",
    },
    "cinematic_studio_3_0": {
        "name": "Cinema Studio 3.0", "provider": "Higgsfield", "badge": "C",
        "blurb": "Higgsfield's cinema-grade model. Hero shots, genre looks.",
        "best_for": ["cinematic"],
        "strengths": {"cinematic": 10, "realism": 9, "broll": 8, "product": 8, "value": 2},
        "durations": {"min": 4, "max": 15},
        "resolutions": {"720p": {"resolution": "720p"}, "1080p": {"resolution": "1080p"}, "4k": {"resolution": "4k"}},
        "audio": {"param": "generate_audio", "on": True, "off": False},
        "frames": {"start": "start_image", "end": "end_image"},
        "aspects": ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"],
        "price": {"720p": {"sound": 6.0, "silent": 6.0}, "1080p": {"sound": 10.0, "silent": 10.0}},
        "watch": "Expensive — use for the one hero shot.",
    },
}

IMAGE = {
    "gpt_image_2": {
        "name": "GPT Image 2", "provider": "OpenAI", "badge": "O",
        "blurb": "Most controllable photoreal frames. Best at edits and product detail.",
        "strengths": {"product": 9, "people": 8, "edit": 10, "text": 9, "realism": 8, "value": 5},
        "resolutions": {"1k": {"resolution": "1k", "quality": "high"}, "2k": {"resolution": "2k", "quality": "high"}},
        "ref_role": "image", "price": {"1k": 3.5, "2k": 6.5},
        "watch": "Refuses some swimwear and body-shape references — describe fabric, not anatomy.",
    },
    "gpt_image_2_5": {
        "name": "GPT Image 2.5", "provider": "OpenAI", "badge": "O",
        "blurb": "Higgsfield's default image model. Great all-rounder, cheap at medium.",
        "strengths": {"product": 8, "people": 8, "edit": 9, "text": 9, "realism": 8, "value": 9},
        "resolutions": {"1k": {"resolution": "1k", "quality": "medium"}, "2k": {"resolution": "2k", "quality": "high"}},
        "ref_role": "image_references", "price": {"1k": 1.0, "2k": 4.0},
        "watch": "",
    },
    "soul_2": {
        "name": "Soul 2.0", "provider": "Higgsfield", "badge": "S",
        "blurb": "Realistic UGC people and fashion. Almost free.",
        "strengths": {"people": 10, "ugc": 10, "realism": 9, "product": 5, "edit": 5, "value": 10},
        "resolutions": {"1k": {"quality": "1.5k"}, "2k": {"quality": "2k"}},
        "ref_role": "image", "price": {"1k": 0.12, "2k": 0.12},
        "watch": "One reference image only; weaker at exact product detail.",
    },
    "nano_banana_pro": {
        "name": "Nano Banana Pro", "provider": "Google", "badge": "N",
        "blurb": "Top quality with legible text and packaging.",
        "strengths": {"text": 10, "product": 9, "realism": 9, "people": 8, "edit": 8, "value": 7},
        "resolutions": {"1k": {"resolution": "1k"}, "2k": {"resolution": "2k"}},
        "ref_role": "image_references", "price": {"1k": 2.0, "2k": 2.0},
        "watch": "",
    },
    "seedream_v5_pro": {
        "name": "Seedream 5.0 Pro", "provider": "ByteDance", "badge": "S",
        "blurb": "Accepts references other models refuse. Natural, un-glossy look.",
        "strengths": {"people": 8, "product": 8, "edit": 8, "realism": 9, "value": 7},
        "resolutions": {"1k": {"resolution": "1k"}, "2k": {"resolution": "2k"}},
        "ref_role": "image_references", "price": {"1k": 3.0, "2k": 3.0},
        "watch": "",
    },
}

RESOLUTIONS = ["720p", "1080p"]
IMAGE_RES_FOR = {"720p": "1k", "1080p": "2k", "4k": "2k"}


def video_price(model_id, resolution, seconds, sound=True):
    m = VIDEO.get(model_id) or {}
    p = (m.get("price") or {}).get(resolution) or next(iter((m.get("price") or {"x": {}}).values()))
    rate = p.get("sound" if sound else "silent") or p.get("sound") or p.get("silent") or 3.0
    return round(rate * float(seconds), 2)


def image_price(model_id, resolution):
    m = IMAGE.get(model_id) or {}
    res = IMAGE_RES_FOR.get(resolution, "1k")
    return float((m.get("price") or {}).get(res, 3.0))


def snap_duration(model_id, seconds, at_least=False):
    """A duration the model actually accepts: the nearest one, or with `at_least`
    the shortest one that still fits — a talking shot rounded down loses the
    end of its line."""
    d = (VIDEO.get(model_id) or {}).get("durations") or {}
    s = float(seconds)
    s = int(math.ceil(s - 1e-6)) if at_least else int(round(s))
    if "options" in d:
        if at_least:
            fits = [o for o in d["options"] if o >= s]
            return min(fits) if fits else max(d["options"])
        return min(d["options"], key=lambda o: (abs(o - s), -o))
    return max(d.get("min", 3), min(d.get("max", 15), s))


def supported_resolution(model_id, wanted):
    res = list(((VIDEO.get(model_id) or {}).get("resolutions") or {}).keys())
    if wanted in res:
        return wanted
    return res[-1] if res else wanted


def build_video_params(model_id, *, prompt, resolution, seconds, aspect, audio,
                       start_media=None, end_media=None, at_least=False):
    """MCP generate_video params for one shot, mapped to what this model accepts."""
    m = VIDEO[model_id]
    res = supported_resolution(model_id, resolution)
    p = {"model": model_id, "prompt": prompt, "duration": snap_duration(model_id, seconds, at_least)}
    if aspect in m.get("aspects", []):
        p["aspect_ratio"] = aspect
    p.update(m.get("resolutions", {}).get(res, {}))
    p.update(m.get("fixed", {}))
    a = m.get("audio")
    if a:
        p[a["param"]] = a["on"] if audio else a["off"]
    medias = []
    if start_media and m["frames"].get("start"):
        medias.append({"role": m["frames"]["start"], "value": start_media})
    if end_media and m["frames"].get("end"):
        medias.append({"role": m["frames"]["end"], "value": end_media})
    if medias:
        p["medias"] = medias
    return p, res


def build_image_params(model_id, *, prompt, resolution, aspect, refs=None):
    m = IMAGE[model_id]
    res = IMAGE_RES_FOR.get(resolution, "1k")
    p = {"model": model_id, "prompt": prompt, "aspect_ratio": aspect}
    p.update(m.get("resolutions", {}).get(res, {}))
    refs = [r for r in (refs or []) if r]
    if refs:
        if model_id == "soul_2":
            refs = refs[:1]
        p["medias"] = [{"role": m.get("ref_role", "image"), "value": r} for r in refs]
    return p


def public(kind="video", resolution="720p", seconds=5):
    """Catalogue as the UI sees it, with a price quote per model at this resolution."""
    out = []
    src = VIDEO if kind == "video" else IMAGE
    for mid, m in src.items():
        item = {"id": mid, "name": m["name"], "provider": m["provider"], "badge": m["badge"],
                "blurb": m["blurb"], "watch": m.get("watch", "")}
        if kind == "video":
            item.update({
                "resolutions": list(m["resolutions"].keys()),
                "durations": m["durations"],
                "audio": bool(m.get("audio")) or bool(m.get("native_audio")),
                "end_frame": "end" in m["frames"],
                "price": video_price(mid, supported_resolution(mid, resolution), seconds),
                "price_res": supported_resolution(mid, resolution),
            })
        else:
            item.update({"price": image_price(mid, resolution),
                         "references": True})
        out.append(item)
    return out
