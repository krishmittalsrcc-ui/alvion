"""Model router — ALVION suggests a model per role, the user can swap any of them.

One ad uses several models, the way Krish actually works:
  talking shots  (someone speaking on camera)  → lip sync, faces, human motion
  B-roll         (silent cutaways, product)    → references, product, motion, cinema
  frames         (the start image of each shot)→ product detail, people, edits

Every suggestion comes with plain-English reasons and a real price, and ranked
alternatives the user can pick instead. Rankings blend Krish's production results
with published 2026 comparisons (docs/knowledge-sources.md); prices are Higgsfield's.
"""
from . import catalog

INTENTS = {
    "avatar":    {"label": "Avatar / spokesperson", "blurb": "A person talking to camera, selling or explaining.",
                  "dialogue": True, "broll": ["product", "references", "broll"]},
    "ugc":       {"label": "UGC / testimonial", "blurb": "Handheld, first-person, feels like a real customer filmed it.",
                  "dialogue": True, "broll": ["product", "references", "broll"]},
    "product":   {"label": "Product demo", "blurb": "The product itself — held, used, shown close.",
                  "dialogue": False, "broll": ["product", "references", "cinematic"]},
    "cinematic": {"label": "Cinematic / B-roll", "blurb": "Atmosphere, lifestyle, scene-setting shots.",
                  "dialogue": False, "broll": ["cinematic", "realism", "broll"]},
    "motion":    {"label": "Dance / high motion", "blurb": "Bodies moving, fast cuts, energy, transitions.",
                  "dialogue": False, "broll": ["motion", "human_motion", "broll"]},
    "explainer": {"label": "Voiceover explainer", "blurb": "Narration over silent B-roll that illustrates the point.",
                  "dialogue": False, "broll": ["broll", "cinematic", "realism"]},
    "silent":    {"label": "Silent / text cards", "blurb": "No voice. Music, motion and typed cards carry it.",
                  "dialogue": False, "broll": ["broll", "cinematic", "motion"]},
}

TALKING_NEEDS = ["talking", "lip_sync", "human_motion"]
WEIGHTS = (3.0, 2.0, 1.0)


def _score(m, needs, value_weight):
    s = m.get("strengths", {})
    total = sum(w * s.get(n, 0) for n, w in zip(needs, WEIGHTS))
    return total + value_weight * s.get("value", 5)


def _rank_video(needs, resolution, seconds, value_weight, need_audio=False):
    items = []
    for mid, m in catalog.VIDEO.items():
        if need_audio and not (m.get("audio") or m.get("native_audio")):
            continue
        items.append((mid, _score(m, needs, value_weight)))
    items.sort(key=lambda kv: kv[1], reverse=True)
    out = []
    for mid, sc in items:
        m = catalog.VIDEO[mid]
        res = catalog.supported_resolution(mid, resolution)
        out.append({"id": mid, "name": m["name"], "provider": m["provider"], "badge": m["badge"],
                    "blurb": m["blurb"], "watch": m.get("watch", ""), "score": round(sc, 1),
                    "price_5s": catalog.video_price(mid, res, seconds, sound=need_audio),
                    "resolution": res, "resolution_note": "" if res == resolution else
                    "%s only goes to %s" % (m["name"], res)})
    return out


def _rank_image(needs, resolution, value_weight):
    items = sorted(catalog.IMAGE.items(), key=lambda kv: _score(kv[1], needs, value_weight), reverse=True)
    return [{"id": mid, "name": m["name"], "provider": m["provider"], "badge": m["badge"],
             "blurb": m["blurb"], "watch": m.get("watch", ""),
             "price": catalog.image_price(mid, resolution)} for mid, m in items]


def choose(video_kind, resolution="720p", has_reference=False, needs_text_in_frame=False,
           audio_mode="native", budget=False, picks=None, **_ignored):
    """Suggested model per role, with ranked alternatives and reasons.

    `picks` are the user's own choices per role; the reasons describe what will
    actually run, and say which suggestion a pick replaced."""
    intent = INTENTS.get(video_kind) or INTENTS["avatar"]
    resolution = resolution if resolution in ("720p", "1080p") else "720p"
    vw = 5.0 if budget else 0.8
    talking_needed = intent["dialogue"]

    roles = {}
    if talking_needed:
        t = _rank_video(TALKING_NEEDS, resolution, 5, vw, need_audio=audio_mode == "native")
        roles["talking"] = {"label": "Talking shots", "hint": "Someone speaking on camera",
                            "suggested": t[0]["id"], "options": t}
    b = _rank_video(intent["broll"], resolution, 5, vw)
    roles["broll"] = {"label": "B-roll" if talking_needed else "Shots",
                      "hint": "Silent cutaways and product shots" if talking_needed else "Every clip in this ad",
                      "suggested": b[0]["id"], "options": b}

    img_needs = ["product", "edit", "people"]
    if video_kind in ("ugc", "avatar") and not has_reference:
        img_needs = ["people", "ugc", "realism"]
    if needs_text_in_frame:
        img_needs = ["text"] + img_needs
    f = _rank_image(img_needs, resolution, vw)
    roles["frames"] = {"label": "Frames", "hint": "The start image of every shot",
                       "suggested": f[0]["id"], "options": f}

    return {"intent": video_kind, "intent_label": intent["label"], "resolution": resolution,
            "roles": roles, "reasons": _reasons(roles, video_kind, resolution, has_reference, budget, picks or {})}


def _name(role, mid=None):
    s = mid or role["suggested"]
    return next((o["name"] for o in role["options"] if o["id"] == s), s)


def _chosen(roles, k, picks):
    """The model that will run for role k: the user's pick when it is a valid option."""
    p = picks.get(k)
    return p if p and any(o["id"] == p for o in roles[k]["options"]) else roles[k]["suggested"]


def _line(roles, k, picks, what, table):
    mid = _chosen(roles, k, picks)
    line = "**%s** for %s — %s" % (_name(roles[k], mid), what, table[mid]["blurb"])
    if mid != roles[k]["suggested"]:
        line += " *Your pick; ALVION suggested %s.*" % _name(roles[k])
    return line


def _reasons(roles, kind, resolution, has_ref, budget, picks):
    out = []
    if "talking" in roles:
        out.append(_line(roles, "talking", picks, "talking shots", catalog.VIDEO))
    br = _chosen(roles, "broll", picks)
    out.append(_line(roles, "broll", picks, "B-roll" if "talking" in roles else "every shot", catalog.VIDEO))
    out.append(_line(roles, "frames", picks, "frames", catalog.IMAGE))
    if "talking" in roles and _chosen(roles, "talking", picks) != br:
        out.append("Different models for talking and B-roll: each shot goes to the model that's "
                   "best at it. The edit joins them.")
    if has_ref:
        out.append("You attached references — frames and B-roll use models that follow a supplied "
                   "image instead of inventing one.")
    if budget:
        out.append("Budget mode: price weighs more heavily in every pick.")
    if resolution == "1080p":
        out.append("1080p costs roughly 1.3–1.7× more per second. Review at 720p, then re-run the "
                   "approved shots at 1080p if you need to.")
    return out


def summary_line(choice):
    r = choice["roles"]
    parts = []
    if "talking" in r:
        parts.append("talking: " + _name(r["talking"]))
    parts.append(("b-roll: " if "talking" in r else "shots: ") + _name(r["broll"]))
    parts.append("frames: " + _name(r["frames"]))
    return " · ".join(parts) + " · " + choice["resolution"]
