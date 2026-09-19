"""Connect Higgsfield the way Claude does — OAuth sign-in, then MCP.

The user clicks "Connect Higgsfield". A popup opens Higgsfield's own sign-in (so a
logged-in browser is one click), the user approves, Higgsfield redirects back to
ALVION with a code, and ALVION exchanges it for tokens. From then on generations run
against the user's own Higgsfield plan through https://mcp.higgsfield.ai/mcp.

Standards used — nothing Higgsfield-private:
  RFC 9728  protected-resource metadata  (which auth server guards the MCP)
  RFC 8414  authorization-server metadata (its endpoints)
  RFC 7591  dynamic client registration   (ALVION registers itself once)
  RFC 7636  PKCE                           (no client secret on the user's machine)
  RFC 8707  resource indicators            (token is bound to the MCP resource)
  MCP 2025-06-18 Streamable HTTP transport
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse

import httpx

from . import config

RESOURCE = "https://mcp.higgsfield.ai/mcp"
PRM_URL = "https://mcp.higgsfield.ai/.well-known/oauth-protected-resource/mcp"
SCOPES = "openid email offline_access"
PROTOCOL = "2025-06-18"
CLIENTS_PATH = os.path.join(config.DATA_DIR, "oauth_clients.json")

_pending = {}          # state -> {user_id, verifier, redirect_uri, created}
_lock = threading.Lock()


class HFAuthError(RuntimeError):
    pass


class HFError(RuntimeError):
    pass


# --- discovery + registration -------------------------------------------------

_meta_cache = {}


def discover():
    if "as" in _meta_cache and time.time() - _meta_cache["t"] < 3600:
        return _meta_cache["as"]
    prm = httpx.get(PRM_URL, timeout=20).json()
    issuer = (prm.get("authorization_servers") or ["https://clerk.higgsfield.ai"])[0]
    asm = httpx.get(issuer.rstrip("/") + "/.well-known/oauth-authorization-server", timeout=20).json()
    for k in ("authorization_endpoint", "token_endpoint"):
        if k not in asm:
            raise HFAuthError("Higgsfield's sign-in server did not publish %s." % k)
    _meta_cache.update({"as": asm, "t": time.time()})
    return asm


def _load_clients():
    try:
        with open(CLIENTS_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def ensure_client(redirect_uri):
    """Register ALVION with Higgsfield's auth server once per redirect URI."""
    asm = discover()
    key = "%s|%s" % (asm["issuer"], redirect_uri)
    clients = _load_clients()
    if key in clients:
        return clients[key]["client_id"]
    if not asm.get("registration_endpoint"):
        raise HFAuthError("Higgsfield does not allow apps to register themselves.")
    r = httpx.post(asm["registration_endpoint"], timeout=20, json={
        "client_name": "ALVION",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPES,
    })
    if r.status_code >= 300:
        raise HFAuthError("Higgsfield refused to register ALVION (%s): %s" % (r.status_code, r.text[:200]))
    cid = r.json()["client_id"]
    clients[key] = {"client_id": cid, "registered_at": time.time()}
    with open(CLIENTS_PATH, "w") as f:
        json.dump(clients, f, indent=2)
    return cid


# --- the authorization-code + PKCE flow ------------------------------------

def start(user_id, redirect_uri):
    asm = discover()
    client_id = ensure_client(redirect_uri)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    with _lock:
        for s in [s for s, v in _pending.items() if time.time() - v["created"] > 900]:
            _pending.pop(s, None)
        _pending[state] = {"user_id": user_id, "verifier": verifier,
                           "redirect_uri": redirect_uri, "client_id": client_id, "created": time.time()}
    q = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "scope": SCOPES, "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "resource": RESOURCE, "prompt": "consent",
    })
    return asm["authorization_endpoint"] + "?" + q


def finish(state, code):
    with _lock:
        p = _pending.pop(state, None)
    if not p:
        raise HFAuthError("This sign-in link expired or was already used. Start again.")
    asm = discover()
    r = httpx.post(asm["token_endpoint"], timeout=30, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": p["redirect_uri"],
        "client_id": p["client_id"], "code_verifier": p["verifier"], "resource": RESOURCE,
    })
    if r.status_code >= 300:
        raise HFAuthError("Higgsfield rejected the sign-in (%s): %s" % (r.status_code, r.text[:200]))
    return p["user_id"], _token_record(r.json(), p["client_id"])


def _token_record(tok, client_id):
    rec = {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token"),
           "expires_at": time.time() + int(tok.get("expires_in") or 3600) - 60,
           "client_id": client_id, "scope": tok.get("scope")}
    idt = tok.get("id_token")
    if idt:
        try:
            payload = idt.split(".")[1] + "=="
            claims = json.loads(base64.urlsafe_b64decode(payload))
            rec["email"] = claims.get("email")
            rec["account"] = claims.get("sub")
        except Exception:
            pass
    return rec


def refresh(rec):
    if not rec.get("refresh_token"):
        raise HFAuthError("Your Higgsfield session expired. Reconnect Higgsfield.")
    asm = discover()
    r = httpx.post(asm["token_endpoint"], timeout=30, data={
        "grant_type": "refresh_token", "refresh_token": rec["refresh_token"],
        "client_id": rec["client_id"], "resource": RESOURCE,
    })
    if r.status_code >= 300:
        raise HFAuthError("Your Higgsfield session expired. Reconnect Higgsfield.")
    new = _token_record(r.json(), rec["client_id"])
    new.setdefault("email", rec.get("email"))
    if not new.get("refresh_token"):
        new["refresh_token"] = rec["refresh_token"]
    return new


# --- MCP over Streamable HTTP ----------------------------------------------

class MCPClient:
    """Minimal MCP client: initialize once, then tools/call."""

    def __init__(self, token_getter):
        self._token = token_getter          # () -> access token, refreshing if needed
        self._session = None
        self._id = 0
        self._http = httpx.Client(timeout=120)

    def _headers(self):
        h = {"Authorization": "Bearer " + self._token(), "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": PROTOCOL}
        if self._session:
            h["Mcp-Session-Id"] = self._session
        return h

    def _post(self, payload):
        r = self._http.post(RESOURCE, headers=self._headers(), content=json.dumps(payload))
        if r.status_code == 401:
            raise HFAuthError("Higgsfield rejected the connection. Reconnect Higgsfield.")
        if r.status_code == 404 and self._session:
            self._session = None                           # session expired — start a new one
            raise HFError("session-expired")
        if r.status_code >= 400:
            raise HFError("Higgsfield MCP error %s: %s" % (r.status_code, r.text[:300]))
        sid = r.headers.get("mcp-session-id")
        if sid:
            self._session = sid
        if "id" not in payload:
            return None
        ctype = r.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    try:
                        msg = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if msg.get("id") == payload["id"]:
                        return msg
            raise HFError("Higgsfield MCP stream ended without a reply.")
        return r.json() if r.content else None

    def _rpc(self, method, params=None):
        self._id += 1
        msg = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        if msg and msg.get("error"):
            raise HFError("Higgsfield MCP: %s" % msg["error"].get("message", msg["error"]))
        return (msg or {}).get("result")

    def initialize(self):
        if self._session:
            return
        self._rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                 "clientInfo": {"name": "ALVION", "version": config.VERSION}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, tool, arguments):
        for attempt in (1, 2):
            self.initialize()
            try:
                res = self._rpc("tools/call", {"name": tool, "arguments": arguments})
                break
            except HFError as e:
                if str(e) == "session-expired" and attempt == 1:
                    continue
                raise
        if res is None:
            raise HFError("Higgsfield returned nothing for %s." % tool)
        data = res.get("structuredContent")
        if data is None:
            texts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
            joined = "\n".join(texts).strip()
            try:
                data = json.loads(joined) if joined else {}
            except ValueError:
                data = {"text": joined}
        if res.get("isError"):
            raise HFError("%s failed: %s" % (tool, json.dumps(data)[:400]))
        return data

    def tools(self):
        self.initialize()
        return [t["name"] for t in (self._rpc("tools/list") or {}).get("tools", [])]
