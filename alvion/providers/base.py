"""Provider interface. A provider turns a prompt into a media file on disk."""
import os

import httpx


class ProviderError(RuntimeError):
    pass


class NotConfigured(ProviderError):
    pass


class Provider:
    name = "base"
    is_live = False

    def upload_file(self, path):
        """Return a URL the generation backend can read."""
        raise NotImplementedError

    def run(self, application, arguments, on_status=None):
        """Submit and block until done. Returns the raw result payload."""
        raise NotImplementedError

    @staticmethod
    def media_urls(result):
        """Pull output URLs out of a result payload, images and video alike."""
        urls = []
        if not isinstance(result, dict):
            return urls
        for key in ("images", "audios"):
            for item in result.get(key) or []:
                if isinstance(item, dict) and item.get("url"):
                    urls.append(item["url"])
                elif isinstance(item, str):
                    urls.append(item)
        for key in ("video", "audio", "image"):
            item = result.get(key)
            if isinstance(item, dict) and item.get("url"):
                urls.append(item["url"])
            elif isinstance(item, str):
                urls.append(item)
        return urls

    @staticmethod
    def download(url, dest):
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(65536):
                    f.write(chunk)
        return dest
