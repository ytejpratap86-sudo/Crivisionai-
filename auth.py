"""Email/password auth with signed bearer tokens. User identity ALWAYS comes from the token, never the request body."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Header

from .config import settings
from .db import db, row
from .errors import ApiError


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
        dk = hashlib.scrypt(pw.encode(), salt=base64.b64decode(s), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(h))
    except Exception:
        return False


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(data: str) -> str:
    return _b64(hmac.new(settings.auth_secret.encode(), data.encode(), hashlib.sha256).digest())


def issue_token(user_id: str) -> str:
    payload = _b64(json.dumps({"sub": user_id, "exp": int(time.time()) + settings.token_ttl_seconds}).encode())
    return f"{payload}.{sign('tok:' + payload)}"


def read_token(token: str) -> str | None:
    try:
        payload, sig = token.split(".")
        if not hmac.compare_digest(sig, sign("tok:" + payload)):
            return None
        data = json.loads(_unb64(payload))
        if data["exp"] < time.time():
            return None
        return data["sub"]
    except Exception:
        return None


def current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "AUTH_REQUIRED", "Aage badhne ke liye login karein.")
    uid = read_token(authorization[7:].strip())
    if not uid:
        raise ApiError(401, "AUTH_EXPIRED", "Session khatam ho gaya. Dobara login karein.")
    with db() as c:
        u = row(c, "SELECT id, email, name FROM users WHERE id = ?", uid)
    if not u:
        raise ApiError(401, "AUTH_REQUIRED", "Aage badhne ke liye login karein.")
    return u
