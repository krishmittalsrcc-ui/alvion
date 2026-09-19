"""The staged pipeline. You stay in the loop at every expensive step.

  plan ──► images ──► [you: approve / request changes per image]
       ──► clips  ──► [you: approve / request changes per clip, with QC flags]
       ──► edit   ──► [you: answer the edit questions] ──► render ──► re-render

Every generation runs in a background thread and persists to SQLite, so a restart
never loses paid work. Superseded versions move to _superseded/, never deleted.
Feedback given on any shot becomes a lesson applied to every later generation in
the same video — a mistake caught in clip 2 must not repeat in clip 3.
"""
import os
import shutil
import threading
import traceback

from . import brain, catalog, claude_connect, config, db, editor, media, qc, router, security
from .providers import HiggsfieldMCPProvider, MockProvider, ProviderError
from .providers.higgsfield_mcp import load_tokens

_running = {}
_lock = threading.Lock()
RETRY_ALLOWANCE = 0.25


# --- plumbing ----------------------------------------------------------------

def _creds(user_id, provider):
    row = db.get_credential(user_id, provider)
    if not row:
        return None
    try:
        return security.decrypt(row["enc"])
    except ValueError:
        return None


def provider_for(user_id, job_id):
    """The user's own Higgsfield (OAuth-connected), else the free offline preview."""
    if load_tokens(user_id):
        return HiggsfieldMCPProvider(user_id)
    return MockProvider(os.path.join(config.job_dir(job_id), "inputs"))


def higgsfield_live(user_id):
    return bool(load_tokens(user_id))


def anthropic_key(user_id):
    return _creds(user_id, "anthropic")


def _spawn(key, fn, *args):
    with _lock:
        t = _running.get(key)
        if t and t.is_alive():
            return False
        t = threading.Thread(target=fn, args=args, daemon=True, name="alvion-%s" % key)
        _running[key] = t
    t.start()
    return True


def is_running(job_id):
    with _lock:
        return any(k.startswith(job_id) and t.is_alive() for k, t in _running.items())


def _fail(job_id, exc):
    msg = str(exc) or exc.__class__.__name__
    db.log(job_id, "FAILED: %s" % msg, "error")
    db.update_job(job_id, state="failed", error=msg)


def _ensure_not_stuck(job_id, busy_state, fallback):
    job = db.get_job(job_id)
    if job and job["state"] == busy_state:
        db.log(job_id, "Worker stopped during '%s'." % busy_state, "error")
        db.update_job(job_id, state=fallback)


def _supersede(job_id, path, label):
    if not path or not os.path.exists(path):
        return
    dest_dir = os.path.join(config.job_dir(job_id), "_superseded")
    os.makedirs(dest_dir, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(path))
    if not base.endswith("_" + label):          # clip files already carry their version
        base = "%s_%s" % (base, label)
    dest, n = os.path.join(dest_dir, base + ext), 2
    while os.path.exists(dest):                 # never overwrite an older paid version
        dest, n = os.path.join(dest_dir, "%s_%d%s" % (base, n, ext)), n + 1
    shutil.move(path, dest)


def _lessons(job):
    items = (job.get("params") or {}).get("lessons") or []
    if not items:
        return ""
    return ("\n\nALREADY CAUGHT IN THIS VIDEO — do not repeat: " +
            "; ".join(items[-8:]) + ".")


def _add_lesson(job_id, text):
    job = db.get_job(job_id)
    params = job["params"]
    params.setdefault("lessons", []).append(text.strip().rstrip("."))
    db.update_job(job_id, params=params)


def shot_role(data):
    return "talking" if (data.get("dialogue") or "").strip() and not data.get("mute_in_edit") else "broll"


def shot_model(params, data):
    """The model a shot will use: its own override, else the video's model for its role."""
    if data.get("model") in catalog.VIDEO:
        return data["model"]
    models = params.get("models") or {}
    role = shot_role(data)
    return models.get(role) or models.get("broll") or "kling3_0"


def frames_model(params):
    m = (params.get("models") or {}).get("frames")
    return m if m in catalog.IMAGE else "gpt_image_2"


def default_models(choice):
    return {role: r["suggested"] for role, r in choice["roles"].items()}


# --- estimates ---------------------------------------------------------------

def estimate(job, shots=None, quote=False):
    """Per-shot cost. With Higgsfield connected and quote=True, every number is
    Higgsfield's own get_cost quote; otherwise it's the catalogue price."""
    params = job["params"]
    res = params.get("resolution", "720p")
    fm = frames_model(params)
    rows, img_total, vid_total, quoted = [], 0.0, 0.0, False
    prov = None
    if quote and higgsfield_live(job["user_id"]):
        try:
            prov = provider_for(job["user_id"], job["id"])
        except Exception:
            prov = None
    items = [(s["data"], s) for s in shots] if shots else [(c, None) for c in (job.get("plan") or {}).get("clips", [])]
    for d, sh in items:
        vm = shot_model(params, d)
        talking = shot_role(d) == "talking"
        dur = catalog.snap_duration(vm, d.get("duration", 5), at_least=talking)
        vres = catalog.supported_resolution(vm, res)
        ic = catalog.image_price(fm, res)
        vc = catalog.video_price(vm, vres, dur, sound=talking and params.get("audio_mode") == "native")
        if prov:
            try:
                vp, _ = catalog.build_video_params(vm, prompt="quote", resolution=res, seconds=dur,
                                                   aspect=params.get("aspect_ratio", "9:16"),
                                                   audio=talking and params.get("audio_mode") == "native")
                vp.pop("medias", None)
                vc = prov.cost("video", vp)
                ip = catalog.build_image_params(fm, prompt="quote", resolution=res,
                                                aspect=params.get("aspect_ratio", "9:16"))
                ic = prov.cost("image", ip)
                quoted = True
            except Exception:
                pass
        img_total += ic
        vid_total += vc
        rows.append({"id": d.get("id"), "role": "talking" if talking else "broll", "model": vm,
                     "model_name": catalog.VIDEO[vm]["name"], "seconds": dur, "resolution": vres,
                     "frames": 1, "image_credits": round(ic, 2), "video_credits": round(vc, 2)})
    return {
        "resolution": res, "frames_model": fm, "frames_model_name": catalog.IMAGE[fm]["name"],
        "per_image": catalog.image_price(fm, res),
        "frames": len(rows), "video_seconds": sum(r["seconds"] for r in rows),
        "images": round(img_total * (1 + RETRY_ALLOWANCE), 2),
        "clips": round(vid_total * (1 + RETRY_ALLOWANCE), 2),
        "total": round((img_total + vid_total) * (1 + RETRY_ALLOWANCE), 2),
        "retry_allowance": RETRY_ALLOWANCE, "rows": rows,
        "live": higgsfield_live(job["user_id"]), "quoted": quoted,
    }


# =============================================================================
# Stage 1 — plan
# =============================================================================

def start_planning(job_id):
    return _spawn(job_id + ":plan", _plan, job_id)


def refresh_choice(params):
    """Recompute the router's suggestion for these params (resolution, budget,
    references) and merge in the user's picks, which always win."""
    choice = router.choose(params.get("video_kind", "avatar"),
                           resolution=params.get("resolution", "720p"),
                           has_reference=bool(params.get("references")),
                           needs_text_in_frame=bool(params.get("needs_text_in_frame")),
                           audio_mode=params.get("audio_mode", "native"),
                           budget=bool(params.get("budget")),
                           picks=params.get("models") or {})
    models = default_models(choice)
    models.update({k: v for k, v in (params.get("models") or {}).items()
                   if k in models and (v in catalog.VIDEO or v in catalog.IMAGE)})
    params["model_choice"] = choice
    params["models"] = models
    return choice


def _plan(job_id):
    job = db.get_job(job_id)
    try:
        db.update_job(job_id, state="planning", error=None)
        params = job["params"]
        refresh_choice(params)
        models = params["models"]
        db.update_job(job_id, params=params)
        db.log(job_id, "Models: %s" % " · ".join(
            "%s → %s" % (k, (catalog.VIDEO.get(v) or catalog.IMAGE.get(v))["name"]) for k, v in models.items()))

        key = anthropic_key(job["user_id"])
        if key or claude_connect.profile_works():
            db.log(job_id, "Planning with %s…" % (params.get("planner_model") or config.DEFAULT_PLANNER_MODEL))
            plan = brain.plan(params, key, params.get("planner_model"))
        else:
            db.log(job_id, "No Claude connection — using the basic offline planner.", "warn")
            plan = brain.fallback_plan(params)
        for w in plan.get("warnings", []):
            db.log(job_id, "Note: %s" % w, "warn")
        kr = plan.get("kill_room") or {}
        if kr:
            total = sum(int(kr.get(k, 0)) for k in ("stop", "hold", "product_clarity", "visual_proof",
                                                    "desire", "rememberability", "action", "renderability"))
            db.log(job_id, "Kill room: %s (%d/40) — %s" % (kr.get("verdict", "?").upper(), total,
                                                          kr.get("fatal_weakness", "")))

        db.replace_shots(job_id, plan["clips"])
        job = db.get_job(job_id)
        db.update_job(job_id, plan=plan, estimate=estimate(job, db.list_shots(job_id)),
                      edit=brain.edit_defaults(params, plan),
                      brief={"premise": plan.get("premise"), "angle": plan.get("angle"),
                             "category": plan.get("category"), "hook": plan.get("hook_mechanism")},
                      state="plan_review")
        db.log(job_id, "Plan ready: %d shots, %ss. Review it, then generate the images."
               % (len(plan["clips"]), plan.get("total_duration", 0)))
    except Exception as e:
        traceback.print_exc()
        _fail(job_id, e)
    finally:
        _ensure_not_stuck(job_id, "planning", "failed")


# =============================================================================
# Stage 2 — images
# =============================================================================

def _ref_media(prov, job):
    """Upload/import every reference once per video; cache the media ids."""
    params = job["params"]
    if params.get("ref_media") is not None and params.get("ref_media_live") == prov.is_live:
        return params["ref_media"]
    out = []
    for r in (params.get("references") or []):
        try:
            if r.get("path") and os.path.exists(r["path"]):
                out.append(prov.upload(r["path"]))
            elif r.get("link") and r["link"].lower().split("?")[0].endswith((".png", ".jpg", ".jpeg", ".webp")):
                out.append(prov.import_url(r["link"]))
        except Exception as e:
            db.log(job["id"], "Could not attach reference %s: %s" % (r.get("name"), e), "warn")
    params["ref_media"], params["ref_media_live"] = out, prov.is_live
    db.update_job(job["id"], params=params)
    if out:
        db.log(job["id"], "Attached %d reference image(s) to every frame." % len(out))
    return out


def _gen_image(prov, job, prompt, refs, dest):
    params = job["params"]
    fm = frames_model(params)
    ip = catalog.build_image_params(fm, prompt=prompt + _lessons(job), resolution=params.get("resolution", "720p"),
                                    aspect=params.get("aspect_ratio", "9:16"), refs=refs)
    res = prov.generate("image", ip)
    prov.download(res["url"], dest)
    if prov.is_live:
        db.add_credits(job["id"], catalog.image_price(fm, params.get("resolution", "720p")))
    return res


def start_images(job_id, shot_ids=None):
    return _spawn(job_id + ":images", _images, job_id, shot_ids)


def _images(job_id, shot_ids=None):
    job = db.get_job(job_id)
    try:
        db.update_job(job_id, state="generating_images", error=None)
        prov = provider_for(job["user_id"], job_id)
        refs = _ref_media(prov, db.get_job(job_id))
        db.log(job_id, "Frames on %s at %s." % (catalog.IMAGE[frames_model(job["params"])]["name"],
                                              catalog.IMAGE_RES_FOR.get(job["params"].get("resolution", "720p"))))
        jd = config.job_dir(job_id)
        for sh in db.list_shots(job_id):
            if shot_ids and sh["id"] not in shot_ids:
                continue
            if not shot_ids and sh["image_status"] in ("ready", "approved"):
                continue
            db.update_shot(sh["id"], image_status="generating", error=None)
            try:
                v = sh["image_version"] + 1
                dest = os.path.join(jd, "frames", "%s_v%d.png" % (sh["clip_id"], v))
                db.log(job_id, "Image %s — %s" % (sh["clip_id"], sh["data"].get("shot", "")))
                res = _gen_image(prov, db.get_job(job_id), sh["data"]["image_prompt"], refs, dest)
                data = dict(db.get_shot(sh["id"])["data"], image_job_id=res["job_id"])
                db.update_shot(sh["id"], image_status="ready", image_path=dest, image_url=res["url"],
                               image_version=v, data=data)
                db.add_asset(job_id, "frame", path=dest, url=res["url"], clip_id=sh["clip_id"],
                             request_id=res["job_id"])
            except Exception as e:
                db.update_shot(sh["id"], image_status="failed", error=str(e))
                db.log(job_id, "Image %s failed: %s" % (sh["clip_id"], e), "error")
        db.update_job(job_id, state="images_review")
        db.log(job_id, "Images ready. Approve them, or tell ALVION what to change on any one.")
    except Exception as e:
        traceback.print_exc()
        _fail(job_id, e)
    finally:
        _ensure_not_stuck(job_id, "generating_images", "images_review")


def revise_image(job_id, shot_id, feedback):
    return _spawn("%s:img:%s" % (job_id, shot_id), _revise_image, job_id, shot_id, feedback)


def _revise_image(job_id, shot_id, feedback):
    job = db.get_job(job_id)
    sh = db.get_shot(shot_id, job_id)
    try:
        db.update_shot(shot_id, image_status="generating", image_feedback=feedback, error=None)
        db.log(job_id, "Revising image %s: “%s”" % (sh["clip_id"], feedback))
        _add_lesson(job_id, feedback)
        job = db.get_job(job_id)
        prov = provider_for(job["user_id"], job_id)
        edit_prompt = brain.revise_prompt("image", sh["data"]["image_prompt"], feedback, sh["data"],
                                          anthropic_key(job["user_id"]), job["params"].get("planner_model"))
        # The approved frame is the reference — an edit, not a reroll.
        base = sh["data"].get("image_job_id")
        if not base and sh.get("image_path") and os.path.exists(sh["image_path"]):
            base = prov.upload(sh["image_path"])
        v = sh["image_version"] + 1
        dest = os.path.join(config.job_dir(job_id), "frames", "%s_v%d.png" % (sh["clip_id"], v))
        res = _gen_image(prov, job, edit_prompt, [base] if base else [], dest)
        _supersede(job_id, sh.get("image_path"), "v%d" % sh["image_version"])
        data = dict(sh["data"], image_job_id=res["job_id"])
        data.setdefault("image_history", []).append({"version": sh["image_version"], "feedback": feedback})
        db.update_shot(shot_id, image_status="ready", image_path=dest, image_url=res["url"],
                       image_version=v, data=data)
        db.add_asset(job_id, "frame", path=dest, url=res["url"], clip_id=sh["clip_id"],
                     request_id=res["job_id"], meta={"version": v, "feedback": feedback})
        db.log(job_id, "Image %s updated (v%d)." % (sh["clip_id"], v))
    except Exception as e:
        traceback.print_exc()
        db.update_shot(shot_id, image_status="failed", error=str(e))
        db.log(job_id, "Revision of %s failed: %s" % (sh["clip_id"], e), "error")


# =============================================================================
# Stage 3 — clips
# =============================================================================

def start_clips(job_id, shot_ids=None):
    return _spawn(job_id + ":clips", _clips, job_id, shot_ids)


def _clip_for(prov, job, sh, prompt, dest):
    params = job["params"]
    d = sh["data"]
    vm = shot_model(params, d)
    talking = shot_role(d) == "talking"
    start = d.get("image_job_id") if prov.is_live else None
    if not start:
        start = prov.upload(sh["image_path"])
    audio = talking and params.get("audio_mode") == "native"
    # Talking shots pin the start frame as the end frame when the model allows it:
    # the model has to walk back to the pose, which is what leaves a clean silent tail.
    end = start if (talking and "end" in catalog.VIDEO[vm]["frames"]) else None
    vp, vres = catalog.build_video_params(vm, prompt=prompt + _lessons(job), resolution=params.get("resolution", "720p"),
                                          seconds=d.get("duration", 5), aspect=params.get("aspect_ratio", "9:16"),
                                          audio=audio, start_media=start, end_media=end, at_least=talking)
    res = prov.generate("video", vp,
                        on_status=lambda s, j: s in ("queued", "in_progress") and db.log(job["id"], "  %s: %s" % (sh["clip_id"], s)))
    prov.download(res["url"], dest)
    if prov.is_live:
        db.add_credits(job["id"], catalog.video_price(vm, vres, vp["duration"], sound=audio))
    return res, vm, vres, vp["duration"]


def _run_qc(job, sh, path, live):
    d = dict(sh["data"])
    result = qc.qc_clip(path, d if live else dict(d, dialogue=""), job["params"].get("aspect_ratio", "9:16"))
    if not live:
        result["note"] = ("Offline preview clip — a test tone, not speech, so the dialogue check is "
                          "skipped. Clips from your Higgsfield account get the full check.")
    return result


def _clips(job_id, shot_ids=None):
    job = db.get_job(job_id)
    try:
        db.update_job(job_id, state="generating_clips", error=None)
        prov = provider_for(job["user_id"], job_id)
        jd = config.job_dir(job_id)
        for sh in db.list_shots(job_id):
            if shot_ids and sh["id"] not in shot_ids:
                continue
            if not shot_ids and sh["clip_status"] in ("ready", "approved"):
                continue
            if sh["image_status"] != "approved":
                continue
            db.update_shot(sh["id"], clip_status="generating", error=None)
            try:
                v = sh["clip_version"] + 1
                dest = os.path.join(jd, "clips", "%02d_%s_v%d.mp4" % (sh["idx"] + 1, sh["clip_id"], v))
                job = db.get_job(job_id)
                vm = shot_model(job["params"], sh["data"])
                db.log(job_id, "Clip %s on %s — %ss" % (sh["clip_id"], catalog.VIDEO[vm]["name"],
                                                     catalog.snap_duration(vm, sh["data"].get("duration", 5),
                                                                          at_least=shot_role(sh["data"]) == "talking")))
                res, vm, vres, dur = _clip_for(prov, job, sh, sh["data"]["video_prompt"], dest)
                result = _run_qc(job, sh, dest, prov.is_live)
                data = dict(db.get_shot(sh["id"])["data"], clip_job_id=res["job_id"], rendered_model=vm,
                            rendered_resolution=vres)
                db.update_shot(sh["id"], clip_status="ready", clip_path=dest, clip_url=res["url"],
                               clip_version=v, qc=result, data=data)
                db.add_asset(job_id, "clip", path=dest, url=res["url"], clip_id=sh["clip_id"],
                             request_id=res["job_id"], meta={"model": vm, "resolution": vres})
                db.log(job_id, "Clip %s: QC %s%s" % (
                    sh["clip_id"], result["verdict"],
                    "" if not result["flags"] else " — " + "; ".join(f["text"] for f in result["flags"][:2])),
                    "info" if result["verdict"] == "clean" else "warn")
            except Exception as e:
                db.update_shot(sh["id"], clip_status="failed", error=str(e))
                db.log(job_id, "Clip %s failed: %s" % (sh["clip_id"], e), "error")
        db.update_job(job_id, state="clips_review")
        db.log(job_id, "Clips ready. Watch each one — approve it or say what's wrong.")
    except Exception as e:
        traceback.print_exc()
        _fail(job_id, e)
    finally:
        _ensure_not_stuck(job_id, "generating_clips", "clips_review")


def revise_clip(job_id, shot_id, feedback, model=None):
    return _spawn("%s:clip:%s" % (job_id, shot_id), _revise_clip, job_id, shot_id, feedback, model)


def _revise_clip(job_id, shot_id, feedback, model=None):
    job = db.get_job(job_id)
    sh = db.get_shot(shot_id, job_id)
    try:
        db.update_shot(shot_id, clip_status="generating", clip_feedback=feedback, error=None)
        data = dict(sh["data"])
        if model and model in catalog.VIDEO:
            data["model"] = model
            db.log(job_id, "Clip %s switched to %s." % (sh["clip_id"], catalog.VIDEO[model]["name"]))
        if feedback:
            db.log(job_id, "Revising clip %s: “%s”" % (sh["clip_id"], feedback))
            _add_lesson(job_id, feedback)
            job = db.get_job(job_id)
            data["video_prompt"] = brain.revise_prompt("clip", sh["data"]["video_prompt"], feedback, sh["data"],
                                                       anthropic_key(job["user_id"]), job["params"].get("planner_model"))
            low = feedback.lower()
            if any(k in low for k in ("hard cut", "cut off", "not complete", "longer", "extend", "incomplete")):
                data["duration"] = min(10, int(data.get("duration", 5)) + 2)
        data.setdefault("clip_history", []).append({"version": sh["clip_version"], "feedback": feedback,
                                                    "model": data.get("model")})
        db.update_shot(shot_id, data=data)
        sh = db.get_shot(shot_id, job_id)
        prov = provider_for(job["user_id"], job_id)
        v = sh["clip_version"] + 1
        dest = os.path.join(config.job_dir(job_id), "clips", "%02d_%s_v%d.mp4" % (sh["idx"] + 1, sh["clip_id"], v))
        res, vm, vres, dur = _clip_for(prov, db.get_job(job_id), sh, data["video_prompt"], dest)
        result = _run_qc(job, sh, dest, prov.is_live)
        _supersede(job_id, sh.get("clip_path"), "v%d" % sh["clip_version"])
        data = dict(db.get_shot(shot_id)["data"], clip_job_id=res["job_id"], rendered_model=vm, rendered_resolution=vres)
        db.update_shot(shot_id, clip_status="ready", clip_path=dest, clip_url=res["url"], clip_version=v,
                       qc=result, data=data)
        db.add_asset(job_id, "clip", path=dest, url=res["url"], clip_id=sh["clip_id"],
                     request_id=res["job_id"], meta={"version": v, "feedback": feedback, "model": vm})
        db.log(job_id, "Clip %s updated (v%d on %s), QC %s." % (sh["clip_id"], v, catalog.VIDEO[vm]["name"], result["verdict"]))
    except Exception as e:
        traceback.print_exc()
        db.update_shot(shot_id, clip_status="failed", error=str(e))
        db.log(job_id, "Revision of clip %s failed: %s" % (sh["clip_id"], e), "error")


# =============================================================================
# Stage 4/5 — edit and render
# =============================================================================

def start_render(job_id, settings):
    return _spawn(job_id + ":render", _render, job_id, settings)


def _render(job_id, settings):
    job = db.get_job(job_id)
    try:
        db.update_job(job_id, state="rendering", edit=settings, error=None)
        shots = [s for s in db.list_shots(job_id) if s["clip_status"] == "approved" and s.get("clip_path")]
        if not shots:
            raise editor.EditError("No approved clips to edit.")
        live = bool(_creds(job["user_id"], "higgsfield"))
        cache = {}

        def words(si, shot):
            if not live:
                return []
            sh = shots[si]
            q = (sh.get("qc") or {}).get("metrics") or {}
            if si not in cache:
                try:
                    cache[si] = qc.transcribe_words(sh["clip_path"])
                except Exception:
                    cache[si] = []
            return cache[si]

        edit_shots = [{"clip_path": s["clip_path"], "dialogue": s["data"].get("dialogue", ""),
                       "caption": s["data"].get("caption") or s["data"].get("dialogue", ""),
                       "mute_in_edit": s["data"].get("mute_in_edit"),
                       "duration": s["data"].get("duration")} for s in shots]
        settings = dict(settings, aspect=job["params"].get("aspect_ratio", "9:16"))
        name = (job["params"].get("slug") or "alvion-ad") + "_v%d" % (((job.get("render") or {}).get("version") or 0) + 1)
        result = editor.render(config.job_dir(job_id), edit_shots, settings, name=name,
                               log=lambda m: db.log(job_id, m), word_source=words)
        result["version"] = ((job.get("render") or {}).get("version") or 0) + 1
        db.add_asset(job_id, "final", path=result["output"], meta={
            "duration": result["duration"], "width": result["width"], "height": result["height"],
            "has_audio": result["has_audio"], "loudness": result.get("loudness"),
            "version": result["version"]})
        if result["outputs"].get("textless"):
            db.add_asset(job_id, "final_textless", path=result["outputs"]["textless"],
                         meta={"version": result["version"]})
        db.update_job(job_id, state="completed", render=result)
        db.log(job_id, "Rendered v%d — %.1fs, %sx%s, %s LUFS. Change any answer and re-render."
               % (result["version"], result["duration"] or 0, result["width"], result["height"],
                  (result.get("loudness") or {}).get("lufs", "?")))
        db.log(job_id, "ALVION measured timing, silence and loudness. It cannot hear voice quality "
                       "or judge lip sync — check those on playback.", "warn")
    except Exception as e:
        traceback.print_exc()
        _fail(job_id, e)
    finally:
        _ensure_not_stuck(job_id, "rendering", "edit_setup")
