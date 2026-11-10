"""로그인·회원가입. 표준 라이브러리만 사용한다.

- 비밀번호: scrypt(솔트 16바이트) 해시 저장, 평문은 저장하지 않음
- 토큰: HMAC-SHA256 서명한 `base64(payload).base64(sig)` (payload = 사용자 id·만료시각)
- 서명 키: `.env`의 AUTH_SECRET(없으면 JWT_SECRET). 둘 다 없으면 기동할 때마다 새 키를 만든다(재기동 시 다시 로그인 필요)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import DateTime, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, get_db

log = logging.getLogger("npd.auth")

# .env·Cloud Run에는 JWT_SECRET 이름으로 들어가 있어 둘 다 받는다
SECRET = os.getenv("AUTH_SECRET") or os.getenv("JWT_SECRET") or ""
if not SECRET:
    SECRET = secrets.token_hex(32)
    log.warning("AUTH_SECRET·JWT_SECRET 없음: 임시 키 사용(서버를 다시 켜면 모두 다시 로그인해야 함)")
TOKEN_TTL = int(os.getenv("AUTH_TOKEN_TTL_HOURS", "12")) * 3600
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class User(Base):
    __tablename__ = "npd_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(50))
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------- 비밀번호 ----------
_N, _R, _P = 2**14, 8, 1


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(dk) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), dk)


# ---------- 토큰 ----------
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(data: str) -> str:
    return _b64(hmac.new(SECRET.encode(), data.encode(), hashlib.sha256).digest())


def make_token(uid: int) -> str:
    payload = _b64(json.dumps({"uid": uid, "exp": int(time.time()) + TOKEN_TTL}).encode())
    return f"{payload}.{_sign(payload)}"


def read_token(token: str) -> int | None:
    try:
        payload, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        data = json.loads(_unb64(payload))
        if data["exp"] < time.time():
            return None
        return int(data["uid"])
    except (ValueError, KeyError, TypeError):
        return None


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "로그인이 필요합니다", headers={"WWW-Authenticate": "Bearer"})
    uid = read_token(authorization[7:].strip())
    user = db.get(User, uid) if uid is not None else None
    if user is None:
        raise HTTPException(401, "로그인이 만료되었습니다. 다시 로그인하세요", headers={"WWW-Authenticate": "Bearer"})
    return user


# ---------- 스키마·경로 ----------
class SignupIn(BaseModel):
    email: str = Field(max_length=200)
    name: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("이메일 형식이 아닙니다")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("이름을 입력하세요")
        return v

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("비밀번호는 영문과 숫자를 모두 포함해야 합니다")
        return v


class LoginIn(BaseModel):
    email: str
    password: str


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name}


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", status_code=201)
def signup(body: SignupIn, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(409, "이미 가입된 이메일입니다")
    u = User(email=body.email, name=body.name, password_hash=hash_password(body.password))
    db.add(u)
    db.commit()
    return {"token": make_token(u.id), "user": user_out(u)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if u is None or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "이메일 또는 비밀번호가 맞지 않습니다")
    return {"token": make_token(u.id), "user": user_out(u)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)
