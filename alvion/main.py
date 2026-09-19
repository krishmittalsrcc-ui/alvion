"""ALVION HTTP API + web app."""
import json
import os
import shutil
import time

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import catalog, claude_connect, config, db, hf_mcp, router, security, worker
from .providers import ProviderError
from .providers.higgsfield_mcp import HiggsfieldMCPProvider, save_tokens

app = FastAPI(title=config.APP_NAME, version=config.VERSION)
db.init()

PROVIDERS = ("anthropic", "higgsfield")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def current_user(request: Request):
    user = db.session_user(request.cookies.get(config.SESSION_COOKIE))
    if not user:
        raise HTTPException(401, "Not signed in")
    return user


def _public_user(u):
    return {"id": u["id"], "email": u["email"], "plan": u["plan"],
            "is_admin": bool(u["is_admin"]), "credit_ceiling": u["credit_ceiling"],
            "planner_model": u["planner_model"] or config.DEFAULT_PLANNER_MODEL}


def _safe(name, fallback="file"):
    out = "".join(ch for ch in (name or "") if ch.isalnum() or ch in "._- ")[:80].strip()
    return out or fallback


# --- auth ------------------------------------------------------------------

@app.post("/api/auth/register")
async def register(request: Request, response: Response):
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if "@" not in email or len(password) < 8:
        raise HTTPException(400, "A valid email and a password of at least 8 characters.")
    if db.get_user_by_email(email):
        raise HTTPException(400, "That email is already registered.")
    first = db.user_count() == 0
    pw_hash, salt = security.hash_password(password)
    uid = db.create_user(email, pw_hash, salt, is_admin=first)
    token = security.new_token()
    db.create_session(uid, token, config.SESSION_DAYS)
    response.set_cookie(config.SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=config.SESSION_DAYS * 86400)
    return {"user": _public_user(db.get_user(uid))}


@app.post("/api/auth/login")
async def login(request: Request, response: Response):
    body = await request.json()
    user = db.get_user_by_email(body.get("email") or "")
    if not user or not security.verify_password(body.get("password") or "",
                                                user["pw_hash"], user["pw_salt"]):
        raise HTTPException(401, "Wrong email or password.")
    token = security.new_token()
    db.create_session(user["id"], token, config.SESSION_DAYS)
    response.set_cookie(config.SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=config.SESSION_DAYS * 86400)
    return {"user": _public_user(user)}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    db.delete_session(request.cookies.get(config.SESSION_COOKIE))
    response.delete_cookie(config.SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    creds = db.list_credentials(user["id"])
    return {"user": _public_user(user), "credentials": creds,
            "higgsfield_live": worker.higgsfield_live(user["id"]),
            "credits_spent": db.user_credits_spent(user["id"]),
            "connected": {c["provider"] for c in creds} and
                         {c["provider"]: c["hint"] for c in creds} or {}}


@app.post("/api/me")
async def update_me(request: Request, user=Depends(current_user)):
    body = await request.json()
    fields = {}
    if "credit_ceiling" in body:
        v = body["credit_ceiling"]
        fields["credit_ceiling"] = float(v) if v not in (None, "") else None
    if body.get("planner_model"):
        fields["planner_model"] = str(body["planner_model"]).strip()
    db.update_user(user["id"], **fields)
    return {"user": _public_user(db.get_user(user["id"]))}


# --- connections -----------------------------------------------------------

@app.post("/api/credentials")
async def set_credential(request: Request, user=Depends(current_user)):
    body = await request.json()
    provider = (body.get("provider") or "").strip()
    if provider not in PROVIDERS:
        raise HTTPException(400, "Unknown provider.")

    if provider == "higgsfield":
        raise HTTPException(400, "Connect Higgsfield with the sign-in button — no key needed.")
    value = (body.get("api_key") or "").strip()
    if not value:
        raise HTTPException(400, "An API key is required.")
    hint = security.mask(value)
    try:
        claude_connect.client_for(value).models.list(limit=1)
    except Exception as e:
        raise HTTPException(400, "Anthropic rejected that key: %s" % e)
    db.set_credential(user["id"], provider, security.encrypt(value), hint)
    return {"ok": True, "credentials": db.list_credentials(user["id"])}


@app.delete("/api/credentials/{provider}")
def del_credential(provider: str, user=Depends(current_user)):
    db.delete_credential(user["id"], provider)
    return {"ok": True, "credentials": db.list_credentials(user["id"])}


# --- connections: popup sign-in -------------------------------------------

CLOSE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>ALVION</title>
<style>body{background:#09090b;color:#f5f5f7;font:15px/1.5 -apple-system,sans-serif;display:grid;
place-items:center;height:100vh;margin:0}div{text-align:center}b{color:%s}</style></head>
<body><div><b>%s</b><p>%s</p></div><script>
var o=window.opener;try{o&&o.postMessage(%s,"*")}catch(e){}
// opened as a popup: close it; opened as a plain link: go back to Connections
setTimeout(function(){if(o){window.close()}else{location.href="/?view=connections"}},%d)
</script></body></html>"""


def _close_page(ok, title, text, payload):
    return HTMLResponse(CLOSE_PAGE % ("#34d399" if ok else "#f87171", title, text, payload, 900 if ok else 6000))


@app.get("/oauth/higgsfield/start")
def hf_start(request: Request):
    user = db.session_user(request.cookies.get(config.SESSION_COOKIE))
    if not user:
        return _close_page(False, "Sign in to ALVION first", "Then connect Higgsfield again.",
                           '{"type":"alvion-connect","provider":"higgsfield","ok":false}')
    redirect_uri = str(request.base_url).rstrip("/") + "/oauth/higgsfield/callback"
    try:
        return RedirectResponse(hf_mcp.start(user["id"], redirect_uri))
    except Exception as e:
        return _close_page(False, "Couldn't reach Higgsfield", str(e)[:200],
                           '{"type":"alvion-connect","provider":"higgsfield","ok":false}')


@app.get("/oauth/higgsfield/callback")
def hf_callback(code: str = None, state: str = None, error: str = None, error_description: str = None):
    if error or not code:
        return _close_page(False, "Higgsfield wasn't connected", error_description or error or "No code returned.",
                           '{"type":"alvion-connect","provider":"higgsfield","ok":false}')
    try:
        user_id, rec = hf_mcp.finish(state, code)
        save_tokens(user_id, rec)
        try:
            bal = HiggsfieldMCPProvider(user_id).balance()
            rec["plan"] = bal.get("plan") or bal.get("subscription")
            rec["credits"] = bal.get("credits")
            save_tokens(user_id, rec)
        except Exception:
            pass
    except Exception as e:
        return _close_page(False, "Higgsfield wasn't connected", str(e)[:200],
                           '{"type":"alvion-connect","provider":"higgsfield","ok":false}')
    return _close_page(True, "Higgsfield connected", "You can close this window.",
                       '{"type":"alvion-connect","provider":"higgsfield","ok":true}')


@app.get("/api/connect/status")
def connect_status(user=Depends(current_user)):
    from .providers.higgsfield_mcp import load_tokens
    hf = load_tokens(user["id"])
    a = db.get_credential(user["id"], "anthropic")
    cs = claude_connect.status() if not a else {"ant_installed": bool(claude_connect.ant_path())}
    return {"higgsfield": {"connected": bool(hf), "email": (hf or {}).get("email"),
                           "credits": (hf or {}).get("credits"), "plan": (hf or {}).get("plan")},
            "claude": {"connected": bool(a), "via": (a or {}).get("hint"), **cs}}


@app.get("/api/higgsfield/balance")
def hf_balance(user=Depends(current_user)):
    try:
        return HiggsfieldMCPProvider(user["id"]).balance()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/connect/claude/install")
def claude_install(user=Depends(current_user)):
    try:
        return {"ok": True, **claude_connect.install()}
    except Exception as e:
        raise HTTPException(400, "Install failed: %s" % e)


@app.post("/api/connect/claude/login")
async def claude_login(request: Request, user=Depends(current_user)):
    b = await request.json()
    r = claude_connect.start_login(b.get("mode") or "browser")
    if r.get("needs_install"):
        raise HTTPException(409, "needs_install")
    return r


@app.post("/api/connect/claude/code")
async def claude_code(request: Request, user=Depends(current_user)):
    b = await request.json()
    if not claude_connect.submit_code(b.get("code") or ""):
        raise HTTPException(400, "The sign-in isn't waiting for a code any more. Start again.")
    return {"ok": True}


@app.get("/api/connect/claude/poll")
def claude_poll(user=Depends(current_user)):
    if claude_connect.profile_works():
        db.set_credential(user["id"], "anthropic", security.encrypt("profile:default"),
                          "Signed in with Anthropic")
        return {"connected": True}
    return {"connected": False, **claude_connect.status()}


# --- models ----------------------------------------------------------------

@app.get("/api/catalog")
def model_catalog(resolution: str = "720p", user=Depends(current_user)):
    return {"video": catalog.public("video", resolution), "image": catalog.public("image", resolution),
            "resolutions": catalog.RESOLUTIONS}


# --- brands ----------------------------------------------------------------

@app.get("/api/brands")
def brands(user=Depends(current_user)):
    return {"brands": db.list_brands(user["id"])}


@app.post("/api/brands")
async def create_brand(request: Request, user=Depends(current_user)):
    b = await request.json()
    name = (b.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "A brand needs a name.")
    bid = db.create_brand(user["id"], name, b.get("tagline"), b.get("details"),
                          b.get("accent") or "#5b8cff")
    return {"brand": db.get_brand(bid, user["id"])}


@app.get("/api/brands/{brand_id}")
def brand_detail(brand_id: str, user=Depends(current_user)):
    b = db.get_brand(brand_id, user["id"])
    if not b:
        raise HTTPException(404, "No such brand.")
    b["assets"] = db.list_brand_assets(brand_id, user["id"])
    b["projects"] = db.list_projects(user["id"], brand_id)
    return b


@app.post("/api/brands/{brand_id}")
async def update_brand(brand_id: str, request: Request, user=Depends(current_user)):
    if not db.get_brand(brand_id, user["id"]):
        raise HTTPException(404, "No such brand.")
    b = await request.json()
    fields = {k: b[k] for k in ("name", "tagline", "details", "accent") if k in b}
    db.update_brand(brand_id, user["id"], **fields)
    return {"brand": db.get_brand(brand_id, user["id"])}


@app.delete("/api/brands/{brand_id}")
def remove_brand(brand_id: str, user=Depends(current_user)):
    db.delete_brand(brand_id, user["id"])
    return {"ok": True}


@app.post("/api/brands/{brand_id}/assets")
async def upload_brand_asset(brand_id: str, kind: str = Form("reference"),
                             name: str = Form(None), note: str = Form(None),
                             file: UploadFile = File(...), user=Depends(current_user)):
    if not db.get_brand(brand_id, user["id"]):
        raise HTTPException(404, "No such brand.")
    folder = os.path.join(config.DATA_DIR, "brands", brand_id)
    os.makedirs(folder, exist_ok=True)
    fname = _safe(file.filename, "asset")
    dest = os.path.join(folder, "%d_%s" % (int(time.time() * 1000), fname))
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    aid = db.add_brand_asset(brand_id, user["id"], kind, name or fname, path=dest, note=note)
    return {"ok": True, "asset_id": aid, "assets": db.list_brand_assets(brand_id, user["id"])}


@app.post("/api/brands/{brand_id}/links")
async def add_brand_link(brand_id: str, request: Request, user=Depends(current_user)):
    if not db.get_brand(brand_id, user["id"]):
        raise HTTPException(404, "No such brand.")
    b = await request.json()
    link = (b.get("link") or "").strip()
    if not link.startswith(("http://", "https://")):
        raise HTTPException(400, "Give a full http(s) link.")
    db.add_brand_asset(brand_id, user["id"], b.get("kind") or "link",
                       b.get("name") or link[:60], link=link, note=b.get("note"))
    return {"ok": True, "assets": db.list_brand_assets(brand_id, user["id"])}


@app.get("/api/brand-assets/{asset_id}/file")
def brand_asset_file(asset_id: str, user=Depends(current_user)):
    a = db.get_brand_asset(asset_id, user["id"])
    if not a or not a["path"] or not os.path.exists(a["path"]):
        raise HTTPException(404, "No such asset.")
    return FileResponse(a["path"], filename=os.path.basename(a["path"]))


@app.delete("/api/brand-assets/{asset_id}")
def del_brand_asset(asset_id: str, user=Depends(current_user)):
    db.delete_brand_asset(asset_id, user["id"])
    return {"ok": True}


# --- projects --------------------------------------------------------------

@app.get("/api/projects")
def projects(brand_id: str = None, user=Depends(current_user)):
    return {"projects": db.list_projects(user["id"], brand_id)}


@app.post("/api/projects")
async def create_project(request: Request, user=Depends(current_user)):
    b = await request.json()
    name = (b.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "A project needs a name.")
    pid = db.create_project(user["id"], name, b.get("brand_id") or None, b.get("note"))
    return {"project": db.get_project(pid, user["id"])}


@app.get("/api/projects/{project_id}")
def project_detail(project_id: str, user=Depends(current_user)):
    p = db.get_project(project_id, user["id"])
    if not p:
        raise HTTPException(404, "No such project.")
    p["videos"] = db.list_jobs(user["id"], project_id=project_id)
    if p.get("brand_id"):
        p["brand_assets"] = db.list_brand_assets(p["brand_id"], user["id"])
    return p


@app.delete("/api/projects/{project_id}")
def remove_project(project_id: str, user=Depends(current_user)):
    db.delete_project(project_id, user["id"])
    return {"ok": True}


# --- the router (so the UI can show the choice before committing) ----------

@app.get("/api/intents")
def intents():
    out = []
    for k, v in router.INTENTS.items():
        c = router.choose(k, "720p")
        lead = c["roles"].get("talking") or c["roles"]["broll"]
        names = [next(o["name"] for o in r["options"] if o["id"] == r["suggested"])
                 for key, r in c["roles"].items() if key != "frames"]
        out.append({"key": k, "label": v["label"], "blurb": v["blurb"], "dialogue": v["dialogue"],
                    "video_label": " + ".join(dict.fromkeys(names)),
                    "image_label": next(o["name"] for o in c["roles"]["frames"]["options"]
                                        if o["id"] == c["roles"]["frames"]["suggested"])})
    return {"intents": out}


@app.post("/api/router/preview")
async def router_preview(request: Request, user=Depends(current_user)):
    b = await request.json()
    kind = b.get("video_kind") or "avatar"
    intent = router.INTENTS.get(kind) or router.INTENTS["avatar"]
    return router.choose(kind, resolution=b.get("resolution") or "720p",
                         has_reference=bool(b.get("has_reference")),
                         needs_text_in_frame=bool(b.get("needs_text_in_frame")),
                         audio_mode=b.get("audio_mode") or ("native" if intent["dialogue"] else "none"),
                         budget=bool(b.get("budget")), picks=b.get("models") or {})


# --- videos (jobs) — the staged, human-in-the-loop pipeline ---------------

def _job_or_404(job_id, user):
    job = db.get_job(job_id, user["id"])
    if not job:
        raise HTTPException(404, "No such video.")
    return job


def _check_ceiling(user, amount, what):
    ceiling = user["credit_ceiling"]
    if ceiling and amount > float(ceiling):
        raise HTTPException(400, "%s estimate is %.0f credits — over your %.0f limit. "
                                 "Raise it in Connections or shorten the ad."
                            % (what, amount, float(ceiling)))


@app.post("/api/projects/{project_id}/videos")
async def create_video(project_id: str, request: Request, user=Depends(current_user)):
    """Create a draft. Uploads and links attach next; planning starts on /plan."""
    proj = db.get_project(project_id, user["id"])
    if not proj:
        raise HTTPException(404, "No such project.")
    b = await request.json()
    params = b.get("params") or {}
    kind = params.get("video_kind")
    if kind not in router.INTENTS:
        raise HTTPException(400, "Pick what kind of video this is.")
    if not (params.get("script") or "").strip():
        raise HTTPException(400, "Give ALVION a script or an idea to work from.")
    intent = router.INTENTS[kind]
    params.setdefault("aspect_ratio", "9:16")
    params.setdefault("resolution", "720p")
    if params["resolution"] not in catalog.RESOLUTIONS:
        raise HTTPException(400, "Resolution must be 720p or 1080p.")
    params["models"] = {k: v for k, v in (params.get("models") or {}).items()
                        if (k in ("talking", "broll") and v in catalog.VIDEO) or (k == "frames" and v in catalog.IMAGE)}
    params.setdefault("target_duration", 30)
    params.setdefault("platform", "tiktok")
    params.setdefault("script_mode", "idea")
    params.setdefault("audio_mode", "native" if intent["dialogue"] else "none")
    params.setdefault("captions", True)
    params["planner_model"] = user["planner_model"] or config.DEFAULT_PLANNER_MODEL
    if proj.get("brand_details") and not params.get("brand"):
        params["brand"] = proj["brand_details"]
    params["brand_asset_ids"] = [a for a in (b.get("asset_ids") or []) if db.get_brand_asset(a, user["id"])]
    title = (b.get("title") or "").strip() or "%s — %s" % (proj["name"], intent["label"])
    params["slug"] = "".join(ch if ch.isalnum() else "-" for ch in title.lower())[:40].strip("-")
    jid = db.create_job(user["id"], title, params, project_id=project_id)
    config.job_dir(jid)
    db.log(jid, "Created in %s." % proj["name"])
    return {"job_id": jid}


@app.post("/api/videos/{job_id}/assets")
async def video_upload(job_id: str, file: UploadFile = File(...), user=Depends(current_user)):
    _job_or_404(job_id, user)
    folder = os.path.join(config.job_dir(job_id), "inputs")
    fname = _safe(file.filename, "upload")
    dest = os.path.join(folder, "%d_%s" % (int(time.time() * 1000), fname))
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    ext = os.path.splitext(fname)[1].lower()
    kind = "image" if ext in IMAGE_EXT else ("audio" if ext in (".mp3", ".wav", ".m4a", ".aac") else
                                            ("video" if ext in (".mp4", ".mov", ".webm") else "file"))
    db.add_job_asset(job_id, kind, fname, path=dest)
    return {"ok": True, "assets": db.list_job_assets(job_id)}


@app.post("/api/videos/{job_id}/links")
async def video_link(job_id: str, request: Request, user=Depends(current_user)):
    _job_or_404(job_id, user)
    b = await request.json()
    link = (b.get("link") or "").strip()
    if not link.startswith(("http://", "https://")):
        raise HTTPException(400, "Give a full http(s) link.")
    db.add_job_asset(job_id, "link", b.get("name") or link[:60], link=link)
    return {"ok": True, "assets": db.list_job_assets(job_id)}


@app.get("/api/job-assets/{job_id}/{asset_id}")
def job_asset_file(job_id: str, asset_id: str, user=Depends(current_user)):
    _job_or_404(job_id, user)
    for a in db.list_job_assets(job_id):
        if a["id"] == asset_id and a["path"] and os.path.exists(a["path"]):
            return FileResponse(a["path"])
    raise HTTPException(404, "No such asset.")


@app.post("/api/videos/{job_id}/plan")
def plan_video(job_id: str, user=Depends(current_user)):
    job = _job_or_404(job_id, user)
    if worker.is_running(job_id):
        raise HTTPException(400, "Already working on it.")
    params = job["params"]
    refs = []
    for aid in params.get("brand_asset_ids") or []:
        a = db.get_brand_asset(aid, user["id"])
        if a:
            refs.append({"kind": a["kind"], "name": a["name"], "path": a["path"],
                         "link": a["link"], "note": a["note"]})
    for a in db.list_job_assets(job_id):
        if a["kind"] in ("image", "link"):
            refs.append({"kind": a["kind"], "name": a["name"], "path": a["path"], "link": a["link"]})
        elif a["kind"] == "audio":
            params["supplied_audio"] = a["path"]
    params["references"] = refs
    db.update_job(job_id, params=params)
    worker.start_planning(job_id)
    return {"ok": True}


@app.get("/api/videos")
def all_videos(user=Depends(current_user)):
    return {"videos": db.list_jobs(user["id"])}


def _shot_public(job_id, s):
    d = s["data"]
    return {
        "id": s["id"], "idx": s["idx"], "clip_id": s["clip_id"],
        "plan_role": d.get("role"), "duration": d.get("duration"), "shot": d.get("shot"),
        "location": d.get("location"), "dialogue": d.get("dialogue"), "caption": d.get("caption"),
        "mute": d.get("mute_in_edit"), "image_prompt": d.get("image_prompt"),
        "role": worker.shot_role(d), "model": d.get("model"),
        "model_used": worker.shot_model(db.get_job(job_id)["params"], d),
        "rendered_model": d.get("rendered_model"),
        "video_prompt": d.get("video_prompt"),
        "image_status": s["image_status"], "image_version": s["image_version"],
        "image_feedback": s["image_feedback"],
        "clip_status": s["clip_status"], "clip_version": s["clip_version"],
        "clip_feedback": s["clip_feedback"], "qc": s["qc"], "error": s["error"],
        "image": ("/api/videos/%s/shots/%s/image?v=%d" % (job_id, s["id"], s["image_version"])
                  if s.get("image_path") else None),
        "clip": ("/api/videos/%s/shots/%s/clip?v=%d" % (job_id, s["id"], s["clip_version"])
                 if s.get("clip_path") else None),
    }


@app.get("/api/videos/{job_id}")
def video_detail(job_id: str, user=Depends(current_user)):
    job = _job_or_404(job_id, user)
    job["running"] = worker.is_running(job_id)
    job["shots"] = [_shot_public(job_id, s) for s in db.list_shots(job_id)]
    job["uploads"] = [{"id": a["id"], "kind": a["kind"], "name": a["name"], "link": a["link"],
                       "url": "/api/job-assets/%s/%s" % (job_id, a["id"]) if a["path"] else None}
                      for a in db.list_job_assets(job_id)]
    finals = [a for a in db.list_assets(job_id) if a["kind"] in ("final", "final_textless")]
    job["finals"] = [{"id": a["id"], "kind": a["kind"], "meta": a["meta"],
                      "url": "/api/videos/%s/asset/%s" % (job_id, a["id"])} for a in finals]
    if job.get("project_id"):
        job["project"] = db.get_project(job["project_id"], user["id"])
    return job


@app.get("/api/videos/{job_id}/shots/{shot_id}/{what}")
def shot_file(job_id: str, shot_id: str, what: str, user=Depends(current_user)):
    _job_or_404(job_id, user)
    sh = db.get_shot(shot_id, job_id)
    path = sh and (sh["image_path"] if what == "image" else sh["clip_path"] if what == "clip" else None)
    if not path or not os.path.exists(path):
        raise HTTPException(404, "Not generated yet.")
    return FileResponse(path)


@app.get("/api/videos/{job_id}/events")
def video_events(job_id: str, after: int = 0, user=Depends(current_user)):
    _job_or_404(job_id, user)
    return {"events": db.events_since(job_id, after)}


# ---- models --------------------------------------------------------------

@app.post("/api/videos/{job_id}/models")
async def set_models(job_id: str, request: Request, user=Depends(current_user)):
    job = _job_or_404(job_id, user)
    b = await request.json()
    params = job["params"]
    models = dict(params.get("models") or {})
    for k in ("talking", "broll"):
        if b.get(k):
            if b[k] not in catalog.VIDEO:
                raise HTTPException(400, "Unknown video model %s." % b[k])
            models[k] = b[k]
    if b.get("frames"):
        if b["frames"] not in catalog.IMAGE:
            raise HTTPException(400, "Unknown image model %s." % b["frames"])
        models["frames"] = b["frames"]
    params["models"] = models
    if b.get("resolution"):
        if b["resolution"] not in catalog.RESOLUTIONS:
            raise HTTPException(400, "Resolution must be 720p or 1080p.")
        params["resolution"] = b["resolution"]
    worker.refresh_choice(params)      # re-price the options and re-word the reasons
    db.update_job(job_id, params=params)
    job = db.get_job(job_id)
    db.update_job(job_id, estimate=worker.estimate(job, db.list_shots(job_id)))
    db.log(job_id, "Models set: %s · %s" % (" · ".join("%s %s" % (k, (catalog.VIDEO.get(v) or catalog.IMAGE.get(v))["name"])
                                                      for k, v in models.items()), params.get("resolution")))
    return {"ok": True}


@app.post("/api/videos/{job_id}/shots/{shot_id}/model")
async def set_shot_model(job_id: str, shot_id: str, request: Request, user=Depends(current_user)):
    job = _job_or_404(job_id, user)
    sh = db.get_shot(shot_id, job_id)
    if not sh:
        raise HTTPException(404, "No such shot.")
    b = await request.json()
    m = b.get("model")
    data = dict(sh["data"])
    if m in (None, "", "default"):
        data.pop("model", None)
    elif m in catalog.VIDEO:
        data["model"] = m
    else:
        raise HTTPException(400, "Unknown model.")
    db.update_shot(shot_id, data=data)
    db.update_job(job_id, estimate=worker.estimate(db.get_job(job_id), db.list_shots(job_id)))
    return {"ok": True}


@app.post("/api/videos/{job_id}/quote")
def quote(job_id: str, user=Depends(current_user)):
    job = _job_or_404(job_id, user)
    est = worker.estimate(job, db.list_shots(job_id), quote=True)
    db.update_job(job_id, estimate=est)
    return est


# ---- stage 2: images -------------------------------------------------------

@app.post("/api/videos/{job_id}/images")
async def gen_images(job_id: str, request: Request, user=Depends(current_user)):
    job = _job_or_404(job_id, user)
    if job["state"] not in ("plan_review", "images_review"):
        raise HTTPException(400, "Not ready for images (state: %s)." % job["state"])
    b = await request.json()
    if not b.get("confirm"):
        raise HTTPException(400, "Confirm the image estimate first.")
    job["estimate"] = worker.estimate(job, db.list_shots(job_id))
    _check_ceiling(user, job["estimate"]["images"], "Image")
    db.update_job(job_id, estimate=job["estimate"])
    db.log(job_id, "Approved images — up to ~%.0f credits." % job["estimate"]["images"])
    worker.start_images(job_id)
    return {"ok": True}


async def _feedback(request):
    b = await request.json()
    fb = (b.get("feedback") or "").strip()
    if not fb:
        raise HTTPException(400, "Say what should change.")
    return fb


@app.post("/api/videos/{job_id}/shots/{shot_id}/image/revise")
async def image_revise(job_id: str, shot_id: str, request: Request, user=Depends(current_user)):
    _job_or_404(job_id, user)
    if not db.get_shot(shot_id, job_id):
        raise HTTPException(404, "No such shot.")
    worker.revise_image(job_id, shot_id, await _feedback(request))
    return {"ok": True}


@app.post("/api/videos/{job_id}/shots/{shot_id}/image/regenerate")
def image_regen(job_id: str, shot_id: str, user=Depends(current_user)):
    _job_or_404(job_id, user)
    worker.start_images(job_id, [shot_id])
    return {"ok": True}


@app.post("/api/videos/{job_id}/shots/{shot_id}/image/approve")
def image_approve(job_id: str, shot_id: str, user=Depends(current_user)):
    _job_or_404(job_id, user)
    sh = db.get_shot(shot_id, job_id)
    if not sh or sh["image_status"] not in ("ready", "approved"):
        raise HTTPException(400, "That image isn't ready.")
    db.update_shot(shot_id, image_status="approved")
    return {"ok": True}


@app.post("/api/videos/{job_id}/images/approve-all")
def images_approve_all(job_id: str, user=Depends(current_user)):
    _job_or_404(job_id, user)
    n = 0
    for sh in db.list_shots(job_id):
        if sh["image_status"] == "ready":
            db.update_shot(sh["id"], image_status="approved")
            n += 1
    return {"ok": True, "approved": n}


# ---- stage 3: clips --------------------------------------------------------

@app.post("/api/videos/{job_id}/clips")
async def gen_clips(job_id: str, request: Request, user=Depends(current_user)):
    job = _job_or_404(job_id, user)
    b = await request.json()
    if not b.get("confirm"):
        raise HTTPException(400, "Confirm the clip estimate first.")
    shots = db.list_shots(job_id)
    pending = [s for s in shots if s["image_status"] != "approved"]
    if pending:
        raise HTTPException(400, "Approve every image first (%d waiting)." % len(pending))
    est = worker.estimate(job, shots)
    _check_ceiling(user, est["clips"], "Clip")
    db.update_job(job_id, estimate=est)
    db.log(job_id, "Approved clips — up to ~%.0f credits." % est["clips"])
    worker.start_clips(job_id)
    return {"ok": True}


@app.post("/api/videos/{job_id}/shots/{shot_id}/clip/revise")
async def clip_revise(job_id: str, shot_id: str, request: Request, user=Depends(current_user)):
    _job_or_404(job_id, user)
    if not db.get_shot(shot_id, job_id):
        raise HTTPException(404, "No such shot.")
    b = await request.json()
    fb = (b.get("feedback") or "").strip()
    model = b.get("model")
    if not fb and not model:
        raise HTTPException(400, "Say what should change, or pick another model.")
    if model and model not in catalog.VIDEO:
        raise HTTPException(400, "Unknown model.")
    worker.revise_clip(job_id, shot_id, fb, model)
    return {"ok": True}


@app.post("/api/videos/{job_id}/shots/{shot_id}/clip/approve")
def clip_approve(job_id: str, shot_id: str, user=Depends(current_user)):
    _job_or_404(job_id, user)
    sh = db.get_shot(shot_id, job_id)
    if not sh or sh["clip_status"] not in ("ready", "approved"):
        raise HTTPException(400, "That clip isn't ready.")
    db.update_shot(shot_id, clip_status="approved")
    return {"ok": True}


@app.post("/api/videos/{job_id}/clips/approve-all")
def clips_approve_all(job_id: str, user=Depends(current_user)):
    job = _job_or_404(job_id, user)
    for sh in db.list_shots(job_id):
        if sh["clip_status"] == "ready":
            db.update_shot(sh["id"], clip_status="approved")
    if all(s["clip_status"] == "approved" for s in db.list_shots(job_id)):
        db.update_job(job_id, state="edit_setup")
        db.log(job_id, "All clips approved. Answer the edit questions and render.")
    return {"ok": True}


# ---- stage 4/5: edit -------------------------------------------------------

EDIT_CHOICES = {
    "captions": ("none", "clean", "bold", "karaoke"),
    "pacing": ("natural", "tight", "fast"),
    "transitions": ("cut", "smooth"),
    "look": ("none", "phone", "film"),
    "platform": ("tiktok", "reels", "shorts", "meta", "youtube"),
}


@app.post("/api/videos/{job_id}/render")
async def render_video(job_id: str, request: Request, user=Depends(current_user)):
    job = _job_or_404(job_id, user)
    if job["state"] not in ("edit_setup", "completed", "clips_review"):
        raise HTTPException(400, "Approve the clips first (state: %s)." % job["state"])
    if not any(s["clip_status"] == "approved" for s in db.list_shots(job_id)):
        raise HTTPException(400, "No approved clips to edit.")
    b = await request.json()
    settings = dict(job.get("edit") or {})
    for k, allowed in EDIT_CHOICES.items():
        if k in b:
            if b[k] not in allowed:
                raise HTTPException(400, "Unknown %s: %s" % (k, b[k]))
            settings[k] = b[k]
    for k in ("punch_in", "jcut", "silence_beat", "textless"):
        if k in b:
            settings[k] = bool(b[k])
    if "music" in b:
        m = dict(settings.get("music") or {})
        m.update({k: v for k, v in (b["music"] or {}).items() if k in ("mode", "mood", "bpm", "gain")})
        settings["music"] = m
    worker.start_render(job_id, settings)
    return {"ok": True}


@app.post("/api/videos/{job_id}/cancel")
def cancel(job_id: str, user=Depends(current_user)):
    job = _job_or_404(job_id, user)
    if job["state"] in config.TERMINAL_STATES:
        raise HTTPException(400, "Already finished.")
    db.update_job(job_id, state="canceled")
    db.log(job_id, "Canceled.", "warn")
    return {"ok": True}


@app.post("/api/videos/{job_id}/replan")
def replan(job_id: str, user=Depends(current_user)):
    _job_or_404(job_id, user)
    if worker.is_running(job_id):
        raise HTTPException(400, "Still running.")
    db.log(job_id, "Re-planning.")
    worker.start_planning(job_id)
    return {"ok": True}


@app.get("/api/videos/{job_id}/asset/{asset_id}")
def video_asset(job_id: str, asset_id: str, user=Depends(current_user)):
    _job_or_404(job_id, user)
    for a in db.list_assets(job_id):
        if a["id"] == asset_id and a["path"] and os.path.exists(a["path"]):
            return FileResponse(a["path"], filename=os.path.basename(a["path"]))
    raise HTTPException(404, "No such asset.")


# --- app shell -------------------------------------------------------------

def _stamp(name):
    try:
        return int(os.path.getmtime(os.path.join(config.WEB_DIR, name)))
    except OSError:
        return 0


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the shell with version-stamped assets, so a browser never runs a stale app.js."""
    with open(os.path.join(config.WEB_DIR, "index.html")) as f:
        html = f.read()
    for name in ("app.js", "style.css", "icons.svg"):
        html = html.replace("/static/%s\"" % name, "/static/%s?v=%d\"" % (name, _stamp(name)))
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health():
    return {"app": config.APP_NAME, "version": config.VERSION, "users": db.user_count()}


app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")
