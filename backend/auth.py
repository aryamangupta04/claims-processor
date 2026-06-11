"""JWT-based authentication and authorization."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import HTTPException, Request

SECRET_KEY = os.environ.get("JWT_SECRET", "plum-claims-secret-key-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


def create_token(member_id: str, name: str, role: str) -> str:
    payload = {
        "member_id": member_id,
        "name": name,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(request: Request) -> dict:
    """Extract and verify JWT from Authorization header. Returns the payload."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = auth_header[7:]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_member(request: Request) -> dict:
    """Verify token and return member info."""
    return verify_token(request)


def require_own_data(request: Request, member_id: str) -> dict:
    """Verify token AND check that the user is accessing their own data (prevents IDOR)."""
    payload = verify_token(request)
    if payload["role"] != "admin" and payload["member_id"] != member_id:
        raise HTTPException(status_code=403, detail="You can only access your own data")
    return payload
