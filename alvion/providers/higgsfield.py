"""Higgsfield Cloud provider, via the official higgsfield-client SDK.

Auth is an API key id and secret from console.higgsfield.ai, combined as
"id:secret" — the format the SDK and the REST Authorization header both expect.
"""
from .base import Provider, ProviderError, NotConfigured


class HiggsfieldProvider(Provider):
    name = "higgsfield"
    is_live = True

    def __init__(self, api_key_id, api_key_secret, timeout=180.0):
        if not api_key_id or not api_key_secret:
            raise NotConfigured("Higgsfield API key id and secret are both required.")
        try:
            from higgsfield_client.http.client import SyncClient
        except ImportError as e:
            raise ProviderError(
                "higgsfield-client is not installed. pip install higgsfield-client") from e
        self._client = SyncClient(api_key="%s:%s" % (api_key_id.strip(),
                                                     api_key_secret.strip()),
                                  timeout=timeout)

    def upload_file(self, path):
        return self._client.upload_file(path)

    def run(self, application, arguments, on_status=None):
        """Submit and poll to completion.

        `application` is the model's endpoint path, e.g.
        "kling-video/v2.5-turbo/pro/image-to-video".
        """
        import higgsfield_client as hf

        controller = self._client.submit(application, arguments)
        request_id = getattr(controller, "request_id", None)

        last = None
        for status in controller.poll_request_status():
            label = type(status).__name__
            if label != last and on_status:
                on_status(label, request_id)
            last = label
            if isinstance(status, hf.NSFW):
                raise ProviderError(
                    "Rejected by the content filter (status: nsfw). This fires on "
                    "false positives too — rephrase the prompt, or reference an "
                    "earlier approved generation instead of uploading.")
            if isinstance(status, hf.Failed):
                raise ProviderError("Generation failed: %s"
                                    % (getattr(status, "error", None) or "no detail returned"))
            if isinstance(status, hf.Cancelled):
                raise ProviderError("Generation was cancelled.")

        result = controller.get()
        if isinstance(result, dict):
            result.setdefault("request_id", request_id)
        return result

    def check(self):
        """Cheap credential probe used by the Settings page."""
        try:
            self._client.status(request_id="00000000-0000-0000-0000-000000000000")
        except Exception as e:
            msg = str(e).lower()
            if "401" in msg or "unauthor" in msg or "credential" in msg or "forbidden" in msg:
                raise ProviderError("Higgsfield rejected these credentials (401).")
            # A 404 for a nonexistent request id means auth succeeded.
        return True
