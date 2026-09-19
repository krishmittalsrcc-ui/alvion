"""The planner: Claude turns a brief into a shot-by-shot, prompt-by-prompt plan.

Uses structured outputs so the worker gets a validated object, never prose it has
to parse. The craft knowledge in alvion/knowledge/ is what stops the output being
generic — it is injected into the system prompt on every call.
"""
import json
import os
import re

from . import config

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["premise", "angle", "category", "hook_mechanism", "script", "clips", "music",
                 "claims", "kill_room", "warnings"],
    "properties": {
        "premise": {"type": "string", "description": "The ad in one sentence."},
        "category": {"type": "string",
                     "description": "Product category and its physics in one line, e.g. "
                                    "'Apparel — fit on a real body in motion is the whole ad.'"},
        "hook_mechanism": {"type": "string",
                           "description": "The named attention mechanism frame 1 runs on."},
        "kill_room": {
            "type": "object", "additionalProperties": False,
            "required": ["verdict", "fatal_weakness", "stop", "hold", "product_clarity",
                         "visual_proof", "desire", "rememberability", "action", "renderability"],
            "properties": {
                "verdict": {"type": "string", "enum": ["produce", "patch", "rebuild"]},
                "fatal_weakness": {"type": "string",
                                   "description": "The single biggest weakness, stated first."},
                "stop": {"type": "integer", "minimum": 0, "maximum": 5},
                "hold": {"type": "integer", "minimum": 0, "maximum": 5},
                "product_clarity": {"type": "integer", "minimum": 0, "maximum": 5},
                "visual_proof": {"type": "integer", "minimum": 0, "maximum": 5},
                "desire": {"type": "integer", "minimum": 0, "maximum": 5},
                "rememberability": {"type": "integer", "minimum": 0, "maximum": 5},
                "action": {"type": "integer", "minimum": 0, "maximum": 5},
                "renderability": {"type": "integer", "minimum": 0, "maximum": 5}
            }
        },
        "angle": {"type": "string",
                  "description": "Why someone who scrolled past ten of these stops on this one."},
        "script": {"type": "string", "description": "The final spoken (or on-screen) words."},
        "clips": {
            "type": "array", "minItems": 1, "maxItems": 24,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "role", "duration", "shot", "location", "dialogue",
                             "image_prompt", "video_prompt", "end_frame_mode",
                             "end_frame_prompt", "mute_in_edit", "product_in_frame", "caption"],
                "properties": {
                    "id": {"type": "string", "description": "Short id, e.g. H1, B2, CTA."},
                    "role": {"type": "string",
                             "enum": ["hook", "hook-alt", "problem", "agitation",
                                      "product", "proof", "offer", "cta", "broll"]},
                    "duration": {"type": "integer", "minimum": 4, "maximum": 15},
                    "shot": {"type": "string",
                             "description": "Framing and angle, e.g. 'close-up, slightly low angle'."},
                    "location": {"type": "string",
                                 "description": "Where this clip happens. One location per clip."},
                    "product_in_frame": {"type": "boolean"},
                    "dialogue": {"type": "string",
                                 "description": "Spoken words for this clip. Empty for B-roll."},
                    "image_prompt": {"type": "string",
                                     "description": "Full start-frame prompt, negatives included."},
                    "video_prompt": {"type": "string",
                                     "description": "Motion prompt, negatives included."},
                    "end_frame_mode": {"type": "string", "enum": ["same", "different", "none"]},
                    "end_frame_prompt": {"type": "string",
                                         "description": "Only when end_frame_mode is 'different'; else empty."},
                    "mute_in_edit": {"type": "boolean",
                                     "description": "True for B-roll laid over another clip's audio."},
                    "caption": {"type": "string",
                                "description": "On-screen caption text for this clip. Empty for none."}
                }
            }
        },
        "music": {
            "type": "object", "additionalProperties": False,
            "required": ["mood", "bpm"],
            "properties": {
                "mood": {"type": "string", "enum": ["drive", "warm", "tense", "uplift"]},
                "bpm": {"type": "integer", "minimum": 60, "maximum": 180}
            }
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["claim", "traceable", "platform_risk"],
                "properties": {
                    "claim": {"type": "string"},
                    "traceable": {"type": "boolean",
                                  "description": "True if it traces to supplied brand information."},
                    "platform_risk": {"type": "string", "enum": ["none", "review", "likely-rejected"]}
                }
            }
        },
        "warnings": {"type": "array", "items": {"type": "string"},
                     "description": "Anything the operator must decide or check."}
    }
}


KNOWLEDGE_ORDER = ("craft.md", "story.md", "prompting.md", "models.md")


def _knowledge():
    parts = []
    for name in KNOWLEDGE_ORDER:
        p = os.path.join(config.KNOWLEDGE_DIR, name)
        if os.path.exists(p):
            with open(p) as f:
                parts.append(f.read())
    return "\n\n---\n\n".join(parts)


SYSTEM = """You are the planning engine of ALVIOn, a system that produces finished \
vertical video ads end to end.

You plan the whole ad: the angle, the script, every clip, and the exact prompts \
that will be sent to an image model and a video model. Your output is executed \
literally — nobody rewrites your prompts before they are billed. A vague prompt \
becomes a wasted generation.

The craft rules below are not suggestions. Each one exists because breaking it \
produced a failed, paid-for generation. Follow them exactly.

{knowledge}

# Output discipline
- Run the verify loop from the prompting rules on every prompt, silently, before
  writing it into the plan. Never print the loop.
- Score the plan in `kill_room` honestly: default 3, above 3 only with a reason.
  If product clarity or visual proof is below 3, say rebuild and put why in warnings.
- Write prompts that a model can execute without further interpretation.
- Include the standing negative blocks verbatim in every image and video prompt.
- Durations are integers equal to the real spoken length of that clip's dialogue.
- Alternate hooks (role "hook-alt") must work against the same body clips.
- If the brief asks for something that breaks a craft rule, follow the rule and \
put the conflict in `warnings`.
- If a claim cannot be traced to supplied brand information, either drop it or \
mark it `traceable: false` and warn.
"""


class BrainError(RuntimeError):
    pass


def build_user_prompt(params):
    """Turn the intake form into the planning request."""
    L = []
    L.append("# Ad to plan\n")
    L.append("- Kind of video: %s" % params.get("video_kind", "ugc-talking-head"))
    L.append("- Aspect ratio: %s" % params.get("aspect_ratio", "9:16"))
    L.append("- Target duration: %ss" % params.get("target_duration", 30))
    L.append("- Platform: %s" % (params.get("platform") or "vertical social"))
    L.append("- Audio mode: %s" % params.get("audio_mode", "native"))
    L.append("- Language: %s" % params.get("language", "en"))
    if params.get("quality"):
        L.append("- Quality tier: %s" % params["quality"])

    if params.get("voice_description"):
        L.append("\n## Voice (use this exact string in every dialogue clip prompt)\n%s"
                 % params["voice_description"])
    if params.get("brand"):
        L.append("\n## Brand / product information (the only source of product truth)\n%s"
                 % params["brand"])
    if params.get("script"):
        if params.get("script_mode") == "exact":
            L.append("\n## THE SCRIPT — EXACT. Do not change, trim, reorder or add a single word."
                     " Every word must appear in exactly one clip's dialogue (or caption, for a"
                     " silent ad), in order. Split clips only at sentence or clause boundaries.\n%s"
                     % params["script"])
        else:
            L.append("\n## The idea (write the script from this)\n%s" % params["script"])
    if params.get("instructions"):
        L.append("\n## Custom instructions from the operator\n%s" % params["instructions"])
    refs = params.get("references") or []
    if refs:
        L.append("\n## Reference material the operator supplied")
        for r in refs:
            bits = [r.get("kind", "reference"), r.get("name", "")]
            if r.get("link"):
                bits.append(r["link"])
            if r.get("note"):
                bits.append("— " + r["note"])
            L.append("- " + " · ".join(b for b in bits if b))
        L.append("Write prompts that match these references rather than inventing "
                 "a look. Reference images are attached to the generation calls.")
    if params.get("reference_notes"):
        L.append("\n## Reference notes\n%s" % params["reference_notes"])

    models = params.get("models") or {}
    if models:
        from . import catalog
        L.append("\n## Models ALVION will generate with (size and word each shot for these)")
        for role, mid in models.items():
            m = catalog.VIDEO.get(mid) or catalog.IMAGE.get(mid)
            if not m:
                continue
            extra = ""
            if mid in catalog.VIDEO:
                d = m.get("durations", {})
                extra = " Allowed durations: %s." % (
                    ", ".join(str(x) for x in d["options"]) + "s" if "options" in d
                    else "%s–%ss" % (d.get("min"), d.get("max")))
            L.append("- %s: %s. %s%s %s" % (role, m["name"], m["blurb"], extra, m.get("watch", "")))
        L.append("Talking shots run on the talking model, silent B-roll on the B-roll model. "
                 "Every clip's duration must be one the model allows.")
    kind = params.get("video_kind")
    if kind == "vo-explainer":
        L.append("\nThis is a voiceover explainer: a separate narration track runs "
                 "under silent B-roll. Set mute_in_edit true on every clip and put "
                 "the narration in `dialogue` so it can be timed.")
    elif kind == "silent-text-cards":
        L.append("\nThis ad is silent. No dialogue at all — carry the message with "
                 "`caption` text on each clip and a music bed. Leave `dialogue` empty.")
    else:
        L.append("\nThis is native-audio UGC: dialogue is generated inside each clip "
                 "and those clips are the soundtrack. B-roll is silent video laid over "
                 "them (mute_in_edit true).")

    L.append("\nPlan the ad now. Aim for a total within about 10%% of %ss."
             % params.get("target_duration", 30))
    return "\n".join(L)


def plan(params, api_key, model=None, on_token=None):
    """Call Claude and return a validated plan dict."""
    try:
        import anthropic
    except ImportError as e:
        raise BrainError("anthropic SDK not installed") from e

    from . import claude_connect
    model = model or config.DEFAULT_PLANNER_MODEL
    client = claude_connect.client_for(api_key)

    kwargs = dict(
        model=model,
        max_tokens=32000,
        system=SYSTEM.format(knowledge=_knowledge()),
        messages=[{"role": "user", "content": build_user_prompt(params)}],
        output_config={"effort": config.PLANNER_EFFORT,
                       "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
    )
    # Opus 5 and the 4.6+ family take adaptive thinking; older models would 400.
    if not any(m in model for m in ("haiku", "-3-", "sonnet-4-5")):
        kwargs["thinking"] = {"type": "adaptive"}

    try:
        with client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()
    except anthropic.APIStatusError as e:
        raise BrainError("Claude API error %s: %s" % (e.status_code, e.message)) from e
    except anthropic.APIConnectionError as e:
        raise BrainError("Could not reach the Claude API: %s" % e) from e

    if getattr(msg, "stop_reason", None) == "refusal":
        raise BrainError("Claude declined to plan this brief (stop_reason: refusal).")

    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    if not text.strip():
        raise BrainError("Planner returned no content.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise BrainError("Planner did not return JSON.")
        data = json.loads(m.group(0))

    usage = getattr(msg, "usage", None)
    data["_usage"] = {
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "model": model,
    }
    return _normalise(data, params)


def _normalise(data, params):
    """Enforce the rules the schema cannot express."""
    clips = data.get("clips") or []
    fixed, warnings = [], list(data.get("warnings") or [])
    for i, c in enumerate(clips):
        c["id"] = (c.get("id") or "C%d" % (i + 1)).strip()
        d = int(c.get("duration") or 5)
        if d < 4:
            warnings.append("Clip %s was %ss; raised to the 4s minimum." % (c["id"], d))
            d = 4
        c["duration"] = min(d, 15)
        if c.get("end_frame_mode") == "different" and not (c.get("end_frame_prompt") or "").strip():
            c["end_frame_mode"] = "same"
            warnings.append("Clip %s asked for a different end frame with no prompt; "
                            "pinned start as end instead." % c["id"])
        fixed.append(c)
    data["clips"] = fixed
    if params.get("script_mode") == "exact" and params.get("script"):
        cov = script_coverage(params["script"], fixed)
        data["script_coverage"] = cov
        if cov["missing"]:
            warnings.append("The plan dropped %d script word(s): %s. Re-plan or edit before "
                            "generating." % (len(cov["missing"]), " ".join(cov["missing"][:12])))
        if cov["added"]:
            warnings.append("The plan added word(s) not in the script: %s."
                            % " ".join(cov["added"][:12]))
    data["warnings"] = warnings
    data["total_duration"] = sum(c["duration"] for c in fixed)
    return data


def fallback_plan(params):
    """Deterministic planner used when no Anthropic key is configured.

    Splits the supplied script into >=4s clips. Produces a runnable plan, not a
    good one — the real planner is the product.
    """
    script = (params.get("script") or "").strip() or "Your product, in one line."
    target = int(params.get("target_duration", 30))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]

    def words(xs):
        return sum(len(x.split()) for x in xs)

    # Craft rule: 12-18 words per dialogue clip, split at clause boundaries.
    TARGET, MAX_W = 15, 18
    clips, buf = [], []
    for sentence in sentences:
        pieces = ([p.strip() for p in re.split(r"(?<=[,;:])\s+", sentence) if p.strip()]
                  if len(sentence.split()) > MAX_W else [sentence])
        for piece in pieces:
            # Flush before appending, so a clip never overshoots the word cap.
            if buf and words(buf) + len(piece.split()) > MAX_W:
                clips.append(" ".join(buf))
                buf = []
            buf.append(piece)
            if words(buf) >= TARGET:
                clips.append(" ".join(buf))
                buf = []
    if buf:
        # Only merge a short tail back if the result still fits one clip.
        if clips and words(buf) < 6 and len(clips[-1].split()) + words(buf) <= MAX_W:
            clips[-1] += " " + " ".join(buf)
        else:
            clips.append(" ".join(buf))

    shots = ["medium, three-quarter, chest up", "close-up, slightly low angle",
             "wide, full body", "medium, to camera", "three-quarter, turning"]
    out = []
    for i, line in enumerate(clips[:12]):
        dur = max(4, min(9, int(round(len(line.split()) / 3.5))))
        out.append({
            "id": "C%d" % (i + 1),
            "role": "hook" if i == 0 else ("cta" if i == len(clips) - 1 else "problem"),
            "duration": int(dur),
            "shot": shots[i % len(shots)],
            "dialogue": line,
            "image_prompt": ("%s. Subject facing camera in a resting pose, full face and "
                             "mouth presented to the lens. %s. Natural soft key light. "
                             "no subtitles, no captions, no on-screen text, no watermark, "
                             "no extra limbs, no malformed hands, no duplicated subject"
                             % (shots[i % len(shots)], params.get("brand") or "Neutral interior")),
            "video_prompt": ("Starts speaking within the first second. Small natural motion. "
                             "Silent beats at head and tail are deliberate editing handles and "
                             "must not be filled with speech. no subtitles, no captions, "
                             "no on-screen text, no watermark, no lavalier or clip-on mic, "
                             "no mic wire, no headset, no earbuds"),
            "end_frame_mode": "none",
            "end_frame_prompt": "",
            "location": "the same room throughout",
            "product_in_frame": i > 0,
            "mute_in_edit": params.get("video_kind") in ("explainer", "silent"),
            "caption": line,
        })
    return _normalise({
        "premise": "Auto-generated from the supplied script.",
        "angle": "Fallback planner — no Anthropic key configured.",
        "script": script,
        "clips": out,
        "music": {"mood": "drive", "bpm": 120},
        "category": "Unclassified — no planner key, category physics not applied.",
        "hook_mechanism": "direct address",
        "kill_room": {"verdict": "patch", "fatal_weakness": "Planned mechanically without Claude; "
                      "no hook work, coverage or proof shot design.", "stop": 2, "hold": 2,
                      "product_clarity": 3, "visual_proof": 2, "desire": 2, "rememberability": 2,
                      "action": 3, "renderability": 4},
        "claims": [],
        "warnings": ["Planned without Claude. Add an Anthropic key in Settings for "
                     "real creative planning, shot coverage and prompt craft."],
    }, params)



def _words(text):
    return [w for w in re.sub(r"[^a-z0-9%$' ]+", " ", (text or "").lower()
                              .replace("\u2019", "'")).split() if w]


def script_coverage(script, clips):
    """Did the plan keep every word of an exact script? Measured, not trusted."""
    import difflib
    want = _words(script)
    got = _words(" ".join((c.get("dialogue") or c.get("caption") or "") for c in clips
                          if c.get("role") != "hook-alt"))
    sm = difflib.SequenceMatcher(a=want, b=got, autojunk=False)
    missing, added = [], []
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op in ("delete", "replace"):
            missing += want[a1:a2]
        if op in ("insert", "replace"):
            added += got[b1:b2]
    return {"ratio": round(sm.ratio(), 3), "missing": missing, "added": added}


# ---------------------------------------------------------------------------
# revisions — apply one piece of feedback to one image or one clip
# ---------------------------------------------------------------------------

REVISE_SYSTEM = """You revise one generation prompt for ALVION, an AI ad studio.

The operator looked at a generated {what} and wrote feedback. Apply exactly that
feedback and nothing else. Everything the operator did not mention must survive
unchanged — the identity, product, background, wardrobe, light and framing locks
especially.

{mode_rules}

Follow these rules exactly:

{knowledge}

Return only the revised prompt text. No preamble, no notes, no quotes around it."""

IMAGE_EDIT_RULES = """This revision is an EDIT of the approved image, not a new image. Write it as:
"Keep this photograph exactly the same. Change ONLY <the change>. Do not alter the
pose, face, body, wardrobe, product, lighting, background or framing." Make exactly
one change. If the feedback asks for several things, apply the most important one
fully and list nothing else. If it asks to dial something up or down, say "slightly,
about fifteen percent" unless they gave a size."""

CLIP_RULES = """This is a full video prompt that will be regenerated from the same start image.
Keep its structure, all lock blocks and the verbatim dialogue exactly. Change only
what the feedback targets. If the feedback is about a hard cut or a line being cut
off, add one to two seconds and restate the silent tail handle. If it is about the
background changing, strengthen the BACKGROUND LOCK and remove any camera move."""


def revise_prompt(kind, original, feedback, shot, api_key=None, model=None):
    """kind: 'image' (edit instruction) or 'clip' (full video prompt)."""
    feedback = (feedback or "").strip()
    if not feedback:
        return original
    if api_key:
        try:
            from . import claude_connect
            client = claude_connect.client_for(api_key)
            sys_prompt = REVISE_SYSTEM.format(
                what="image" if kind == "image" else "video clip",
                mode_rules=IMAGE_EDIT_RULES if kind == "image" else CLIP_RULES,
                knowledge=_knowledge())
            user = ("## Shot\n%s — %s\nDialogue: %s\n\n## Current prompt\n%s\n\n"
                    "## Operator feedback\n%s"
                    % (shot.get("id"), shot.get("shot"), shot.get("dialogue") or "(none)",
                       original, feedback))
            kwargs = dict(model=model or config.DEFAULT_PLANNER_MODEL, max_tokens=4000,
                          system=sys_prompt, messages=[{"role": "user", "content": user}],
                          output_config={"effort": "medium"})
            if not any(m in kwargs["model"] for m in ("haiku", "-3-", "sonnet-4-5")):
                kwargs["thinking"] = {"type": "adaptive"}
            msg = client.messages.create(**kwargs)
            if getattr(msg, "stop_reason", None) != "refusal":
                text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
                if text.strip():
                    return text.strip()
        except Exception:
            pass  # fall through to the deterministic revision
    if kind == "image":
        return ("Keep this photograph exactly the same. Change ONLY this: %s. Do not alter the "
                "pose, face, body, wardrobe, product, lighting, background or framing." % feedback)
    return original + ("\n\nREVISION — apply this and change nothing else: %s. The background, "
                       "person and product stay exactly as in the start image." % feedback)


# ---------------------------------------------------------------------------
# edit recommendations — the defaults the edit stage proposes
# ---------------------------------------------------------------------------

def edit_defaults(params, plan):
    kind = params.get("video_kind", "avatar")
    ugc_like = kind in ("avatar", "ugc")
    platform = params.get("platform") or "tiktok"
    if platform not in ("tiktok", "reels", "shorts", "meta", "youtube"):
        platform = "tiktok"
    mood = ((plan or {}).get("music") or {}).get("mood", "drive")
    return {
        "captions": "none" if params.get("captions") is False else
                    ("karaoke" if ugc_like else "clean"),
        "pacing": "fast" if ugc_like else ("tight" if kind in ("product", "explainer") else "natural"),
        "transitions": "smooth" if kind in ("cinematic",) else "cut",
        "look": "phone" if ugc_like else ("film" if kind == "cinematic" else "phone"),
        "punch_in": ugc_like,
        "music": {"mode": "none" if params.get("music_mode") == "none" else "generated",
                  "mood": mood, "bpm": int(((plan or {}).get("music") or {}).get("bpm", 120))},
        "platform": platform,
        "jcut": True,
        "silence_beat": True,
        "textless": True,
    }
