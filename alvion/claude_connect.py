"""Connect Claude by signing in — the way Claude Code does.

Anthropic's official CLI (`ant`) runs a browser sign-in to your Anthropic account and
stores a short-lived, auto-refreshing token profile. The Anthropic SDK reads that
profile automatically, so once signed in ALVION plans with Claude without a pasted key.

What this is not: a Claude.ai Pro/Max subscription cannot be connected to a third-party
product — Anthropic does not offer that, and borrowing another app's sign-in would breach
their terms. Usage is billed to the Anthropic API account you sign in with.

The installer fetches the official release from github.com/anthropics/anthropic-cli and
refuses to install unless the SHA-256 matches Anthropic's published checksums file.
"""
import hashlib
import io
import os
import platform
import shutil
import stat
import subprocess
import zipfile

import httpx

from . import config

BIN_DIR = os.path.join(config.DATA_DIR, "bin")
LOG = os.path.join(config.DATA_DIR, "claude_login.log")
RELEASES = "https://api.github.com/repos/anthropics/anthropic-cli/releases/latest"
_proc = None


def ant_path():
    local = os.path.join(BIN_DIR, "ant")
    if os.path.exists(local):
        return local
    return shutil.which("ant")


def install():
    """Download, checksum-verify and unpack the official `ant` CLI for this Mac."""
    arch = {"x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine(), "amd64")
    osname = {"Darwin": "macos", "Linux": "linux"}.get(platform.system(), "macos")
    rel = httpx.get(RELEASES, timeout=30, follow_redirects=True).json()
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    want = next((n for n in assets if n.endswith("_%s_%s.zip" % (osname, arch))
                 or n.endswith("_%s_%s.tar.gz" % (osname, arch))), None)
    sums = next((n for n in assets if n.endswith("checksums.txt")), None)
    if not want or not sums:
        raise RuntimeError("No official %s/%s build in the latest Anthropic CLI release." % (osname, arch))
    blob = httpx.get(assets[want], timeout=180, follow_redirects=True).content
    table = httpx.get(assets[sums], timeout=30, follow_redirects=True).text
    expected = next((l.split()[0] for l in table.splitlines() if l.strip().endswith(want)), None)
    actual = hashlib.sha256(blob).hexdigest()
    if not expected or expected.lower() != actual:
        raise RuntimeError("Checksum mismatch for %s — refusing to install." % want)
    os.makedirs(BIN_DIR, exist_ok=True)
    dest = os.path.join(BIN_DIR, "ant")
    if want.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            member = next(n for n in z.namelist() if os.path.basename(n) == "ant")
            with z.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    else:
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(blob)) as t:
            member = next(m for m in t.getmembers() if os.path.basename(m.name) == "ant")
            with t.extractfile(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    os.chmod(dest, os.stat(dest).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    subprocess.run(["xattr", "-d", "com.apple.quarantine", dest], capture_output=True)
    return {"path": dest, "version": rel.get("tag_name"), "sha256": actual, "asset": want}


def start_login(mode="browser"):
    """Start Anthropic's sign-in.

    mode="browser": ant opens the default browser and completes via a local callback —
                    nothing to paste; ALVION polls until the profile works.
    mode="popup":   returns the authorize URL for ALVION's own popup; Anthropic's page
                    then shows a code the user pastes back (submit_code).

    `ant auth login --no-browser` prints the URL instead of opening a browser, and
    listens locally for the callback — so the UI can open it in its own popup window.
    If Anthropic's page shows a code to paste instead, submit_code() feeds it back.
    """
    global _proc
    import time
    ant = ant_path()
    if not ant:
        return {"needs_install": True}
    if not (_proc and _proc.poll() is None):
        log = open(LOG, "w")
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        args = [ant, "auth", "login"] + (["--no-browser"] if mode == "popup" else [])
        _proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                                 stdin=subprocess.PIPE, env=env)
        if mode == "browser":
            return {"started": True, "mode": "browser"}
    for _ in range(40):                      # the URL appears within a second or two
        url = login_url()
        if url:
            return {"started": True, "url": url}
        if _proc.poll() is not None:
            break
        time.sleep(0.25)
    return {"started": _proc.poll() is None, "url": login_url(),
            "log": (open(LOG).read()[-400:] if os.path.exists(LOG) else "")}


def submit_code(code):
    if not (_proc and _proc.poll() is None):
        return False
    _proc.stdin.write((code.strip() + "\n").encode())
    _proc.stdin.flush()
    return True


def login_url():
    """If ant printed a sign-in URL, surface it so the UI can open it as a popup too."""
    try:
        text = open(LOG).read()
    except OSError:
        return None
    for tok in text.split():
        if tok.startswith("https://") and ("anthropic" in tok or "claude" in tok):
            return tok.strip().rstrip(".")
    return None


def profile_works():
    """True when the SDK can authenticate from a signed-in profile (no API key)."""
    try:
        import anthropic
        env_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            client = anthropic.Anthropic()
            client.models.list(limit=1)
            return True
        finally:
            if env_key:
                os.environ["ANTHROPIC_API_KEY"] = env_key
    except Exception:
        return False


def status():
    running = bool(_proc and _proc.poll() is None)
    return {"ant_installed": bool(ant_path()), "login_running": running,
            "signed_in": profile_works(), "login_url": login_url() if running else None}


def client_for(key_or_marker):
    """Anthropic client from a stored API key, or from the signed-in profile."""
    import anthropic
    if key_or_marker and not key_or_marker.startswith("profile:"):
        return anthropic.Anthropic(api_key=key_or_marker)
    return anthropic.Anthropic()
