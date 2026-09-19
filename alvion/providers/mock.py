"""Offline provider: renders placeholder media locally.

Lets the whole pipeline — planning, gating, assembly — run with no API keys and
no spend. Selected automatically when a user has no Higgsfield credentials.
"""
import hashlib
import os
import textwrap

from .. import media
from .base import Provider


def _colour(seed):
    h = hashlib.sha256(seed.encode()).digest()
    return (60 + h[0] % 120, 60 + h[1] % 120, 60 + h[2] % 120)


class MockProvider(Provider):
    name = "mock"
    is_live = False

    def __init__(self, workdir):
        self.workdir = workdir
        os.makedirs(workdir, exist_ok=True)

    def upload_file(self, path):
        return "file://" + os.path.abspath(path)

    def run(self, application, arguments, on_status=None):
        if on_status:
            on_status("InProgress", "mock")
        prompt = str(arguments.get("prompt", ""))[:400]
        is_video = "video" in application
        # Duration must be in the key, or two clips of different lengths
        # collide on one cached file.
        key = "%s|%s|%s|%s" % (application, prompt, arguments.get("duration"),
                               arguments.get("aspect_ratio"))
        stem = hashlib.sha256(key.encode()).hexdigest()[:12]

        w, h = self._dims(arguments.get("aspect_ratio", "9:16"))
        png = os.path.join(self.workdir, "mock_%s.png" % stem)
        self._card(png, prompt, application, w, h)

        if not is_video:
            return {"images": [{"url": "file://" + png}], "request_id": "mock-" + stem}

        dur = float(arguments.get("duration", 5) or 5)
        mp4 = os.path.join(self.workdir, "mock_%s.mp4" % stem)
        media.still_to_video(png, mp4, dur, with_tone=bool(arguments.get("generate_audio")))
        return {"video": {"url": "file://" + mp4}, "request_id": "mock-" + stem}

    @staticmethod
    def _dims(ratio):
        table = {"9:16": (1080, 1920), "16:9": (1920, 1080),
                 "1:1": (1080, 1080), "4:5": (1080, 1350)}
        return table.get(ratio, (1080, 1920))

    @staticmethod
    def _card(path, prompt, application, w, h):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (w, h), _colour(prompt or application))
        d = ImageDraw.Draw(img)
        d.rectangle([40, 40, w - 40, h - 40], outline=(255, 255, 255), width=6)
        y = int(h * 0.30)
        d.text((70, y - 60), "MOCK — no credits spent", fill=(255, 220, 120))
        d.text((70, y - 30), application, fill=(200, 230, 255))
        for line in textwrap.wrap(prompt, width=max(20, w // 22))[:18]:
            d.text((70, y), line, fill=(245, 245, 245))
            y += 26
        img.save(path)
        return path

    @staticmethod
    def download(url, dest):
        """Mock URLs are local file paths — copy instead of fetching."""
        import shutil
        src = url[7:] if url.startswith("file://") else url
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        shutil.copyfile(src, dest)
        return dest


    # --- the MCP-shaped interface the pipeline uses ---------------------------
    def upload(self, path):
        return "file://" + os.path.abspath(path)

    def import_url(self, url):
        return url

    def cost(self, kind, params):
        from .. import catalog
        if kind == "image":
            return 0.0
        return 0.0

    def generate(self, kind, params, on_status=None):
        args = {"prompt": params.get("prompt", ""), "aspect_ratio": params.get("aspect_ratio", "9:16"),
                "duration": params.get("duration", 5)}
        a = params.get("sound", params.get("generate_audio"))
        args["generate_audio"] = a in (True, "on") or (a is None and params.get("model", "").startswith(("veo", "gemini")))
        res = self.run(("video/" if kind == "video" else "image/") + params.get("model", "mock"), args, on_status)
        url = self.media_urls(res)[0]
        return {"job_id": res.get("request_id"), "url": url}

    def balance(self):
        return {"credits": None, "plan": "offline preview"}
