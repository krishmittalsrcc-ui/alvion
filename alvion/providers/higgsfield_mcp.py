"""Higgsfield via MCP — the user's own Higgsfield plan, connected by OAuth sign-in.

Every call maps 1:1 onto a Higgsfield MCP tool:
  upload        media_upload → PUT bytes → media_confirm
  import_url    media_import_url
  generate      generate_{image,video}_batch (headless) → jobs_wait until terminal
  cost          generate_{image,video} with get_cost=true (no job is created)
  balance       balance

Behaviours carried over from real use:
  - use_unlim is always sent as false, so a free-trial allowance is never spent
    and the server never stops to ask.
  - Higgsfield sometimes intercepts a submission to recommend a preset. Nothing is
    charged; ALVION resubmits with that preset declined.
  - A timeout does not mean a job failed. Job ids are kept and polled, never
    blindly resubmitted — resubmitting double-charges.
"""
import json
import mimetypes
import os
import time

import httpx

from .. import db, hf_mcp, security
from .base import Provider, ProviderError

TERMINAL = {"completed", "failed", "nsfw", "canceled", "cancelled", "error"}


def load_tokens(user_id):
    row = db.get_credential(user_id, "higgsfield")
    if not row:
        return None
    try:
        raw = security.decrypt(row["enc"])
    except ValueError:
        return None
    if not raw.startswith("{"):
        return None                      # a Cloud API key, not an OAuth connection
    return json.loads(raw)


def save_tokens(user_id, rec):
    db.set_credential(user_id, "higgsfield", security.encrypt(json.dumps(rec)),
                      rec.get("email") or "Higgsfield account")


class HiggsfieldMCPProvider(Provider):
    name = "higgsfield-mcp"
    is_live = True

    def __init__(self, user_id):
        self.user_id = user_id
        if not load_tokens(user_id):
            raise ProviderError("Higgsfield isn't connected.")
        self.client = hf_mcp.MCPClient(self._token)

    def _token(self):
        rec = load_tokens(self.user_id)
        if not rec:
            raise hf_mcp.HFAuthError("Higgsfield isn't connected.")
        if time.time() >= rec.get("expires_at", 0):
            rec = hf_mcp.refresh(rec)
            save_tokens(self.user_id, rec)
        return rec["access_token"]

    # --- media -------------------------------------------------------------
    def upload(self, path):
        name = os.path.basename(path)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        res = self.client.call("media_upload", {"filename": name, "content_type": ctype})
        slot = (res.get("uploads") or [res])[0]
        with open(path, "rb") as f:
            r = httpx.put(slot["upload_url"], content=f.read(),
                          headers={"Content-Type": slot.get("content_type", ctype)}, timeout=300)
        if r.status_code >= 300:
            raise ProviderError("Upload to Higgsfield failed (%s)." % r.status_code)
        kind = ctype.split("/")[0] if ctype.split("/")[0] in ("image", "video", "audio") else "file"
        self.client.call("media_confirm", {"media_id": slot["media_id"], "type": kind})
        return slot["media_id"]

    upload_file = upload

    def import_url(self, url):
        res = self.client.call("media_import_url", {"url": url, "type": "auto"})
        mid = res.get("media_id") or res.get("id")
        if not mid:
            raise ProviderError("Higgsfield could not import %s." % url)
        return mid

    # --- generation --------------------------------------------------------
    def cost(self, kind, params):
        tool = "generate_image" if kind == "image" else "generate_video"
        res = self.client.call(tool, {"params": dict(params, get_cost=True, use_unlim=False)})
        c = res.get("cost") or {}
        return float(c.get("credits_exact", c.get("credits", 0)) or 0)

    def _submit(self, kind, params):
        tool = "generate_image_batch" if kind == "image" else "generate_video_batch"
        p = dict(params, use_unlim=False)
        for _ in range(3):
            res = self.client.call(tool, {"requests": [{"index": 0, "params": p}]})
            jobs = res.get("jobs") or []
            job = next((j for j in jobs if j.get("job_id")), None)
            if job:
                return job["job_id"]
            preset = _find_key(res, "preset_id")
            if preset and not p.get("declined_preset_id"):
                p["declined_preset_id"] = preset          # interception: nothing charged
                continue
            raise ProviderError("Higgsfield did not start the job: %s" % json.dumps(res)[:400])
        raise ProviderError("Higgsfield kept intercepting the submission.")

    def wait(self, job_id, on_status=None, max_seconds=1800):
        start, last = time.time(), None
        while time.time() - start < max_seconds:
            res = self.client.call("jobs_wait", {"jobs": [{"index": 0, "job_id": job_id}],
                                                 "timeout_seconds": 15})
            job = (res.get("jobs") or [{}])[0]
            status = (job.get("status") or "").lower()
            if status != last and on_status:
                on_status(status, job_id)
            last = status
            if status in TERMINAL:
                if status != "completed":
                    raise ProviderError(_why(status, job))
                url = job.get("result_url") or _find_key(job, "url")
                if not url:
                    raise ProviderError("Job finished but returned no file.")
                return url
            time.sleep(max(0, float(res.get("poll_after_seconds") or 0)))
        raise ProviderError("Still generating after %d minutes — job %s is kept, not resubmitted."
                            % (max_seconds // 60, job_id))

    def generate(self, kind, params, on_status=None):
        job_id = self._submit(kind, params)
        if on_status:
            on_status("submitted", job_id)
        url = self.wait(job_id, on_status)
        return {"job_id": job_id, "url": url}

    def balance(self):
        return self.client.call("balance", {})


def _find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj and obj[key]:
            return obj[key]
        for v in obj.values():
            r = _find_key(v, key)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_key(v, key)
            if r:
                return r
    return None


def _why(status, job):
    if status == "nsfw":
        return ("Higgsfield's content filter blocked it (nsfw). This fires on innocent images too — "
                "change the wardrobe or setting, or reference an earlier approved generation.")
    return "Generation %s: %s" % (status, job.get("error") or "no detail from Higgsfield")
