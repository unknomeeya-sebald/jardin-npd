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


def _env_set(key: str, default: str = "") -> frozenset[str]:
    return frozenset(x.strip().lower() for x in os.getenv(key, default).split(",") if x.strip())


# 가입 허용: 이 도메인의 주소이거나, 예외로 적어 둔 주소(쉼표로 여러 개). 도메인을 "*"로 두면 제한 없음
ALLOWED_DOMAINS = _env_set("ALLOWED_EMAIL_DOMAINS", "jardin.co.kr")
ALLOWED_EMAILS = _env_set("ALLOWED_EMAILS")


def email_allowed(email: str) -> bool:
    return "*" in ALLOWED_DOMAINS or email in ALLOWED_EMAILS or email.rsplit("@", 1)[-1] in ALLOWED_DOMAINS


class User(Base):
    __tablename__ = "npd_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(50))
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


RESET_TTL = 10 * 60        # 인증 코드 유효 시간(초)
RESET_RESEND_SEC = 60      # 코드 다시 보내기 최소 간격(초)
RESET_MAX_ATTEMPTS = 5     # 코드 입력 허용 횟수


class PasswordReset(Base):
    """비밀번호 재설정 인증 코드. 사용자당 한 건(다시 요청하면 덮어씀)."""
    __tablename__ = "npd_password_resets"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(Integer)  # epoch 초
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[int] = mapped_column(Integer)     # epoch 초


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


class ForgotIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    email: str
    code: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=8, max_length=128)

    _pw = field_validator("password")(SignupIn._pw.__func__)


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name}


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", status_code=201)
def signup(body: SignupIn, db: Session = Depends(get_db)):
    if not email_allowed(body.email):
        raise HTTPException(403, f"회사 메일(@{', @'.join(sorted(ALLOWED_DOMAINS))})로만 가입할 수 있습니다")
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


# ---------- 비밀번호 찾기 ----------
# 1) /forgot: 6자리 인증 코드를 만들어 본인 Slack DM으로 보낸다(코드는 해시로만 저장)
# 2) /reset : 코드가 맞으면 새 비밀번호로 바꾸고 바로 로그인시킨다
def _code_hash(uid: int, code: str) -> str:
    return hmac.new(SECRET.encode(), f"reset:{uid}:{code}".encode(), hashlib.sha256).hexdigest()


def send_reset_code(email: str, code: str) -> None:
    """인증 코드를 본인에게 전달한다(테스트에서 바꿔 끼운다)."""
    from . import notify

    notify.dm_by_email(
        email,
        f":key: *NPD 일정 관리* 비밀번호 재설정 인증 코드: *{code}*\n"
        f"{RESET_TTL // 60}분 안에 입력하세요. 본인이 요청하지 않았다면 이 메시지를 무시하세요.")


@router.post("/forgot")
def forgot(body: ForgotIn, db: Session = Depends(get_db)):
    from .notify import SlackUserNotFound

    u = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if u is None:
        raise HTTPException(404, "가입되지 않은 이메일입니다. 회원가입을 먼저 하세요")
    now = int(time.time())
    row = db.get(PasswordReset, u.id)
    if row is not None and now - row.sent_at < RESET_RESEND_SEC:
        raise HTTPException(429, f"인증 코드를 방금 보냈습니다. {RESET_RESEND_SEC - (now - row.sent_at)}초 뒤에 다시 시도하세요")
    code = f"{secrets.randbelow(10**6):06d}"
    try:
        send_reset_code(u.email, code)
    except SlackUserNotFound:
        raise HTTPException(422, "이 이메일로 등록된 Slack 계정이 없어 인증 코드를 보낼 수 없습니다. 관리자에게 문의하세요") from None
    except Exception as e:  # noqa: BLE001
        log.warning("비밀번호 재설정 코드 전송 실패: %s", e)
        raise HTTPException(503, "인증 코드를 보내지 못했습니다. 관리자에게 문의하세요") from e
    if row is None:
        row = PasswordReset(user_id=u.id)
        db.add(row)
    row.code_hash, row.expires_at, row.attempts, row.sent_at = _code_hash(u.id, code), now + RESET_TTL, 0, now
    db.commit()
    return {"sent": True, "via": "slack", "ttl_min": RESET_TTL // 60}


@router.post("/reset")
def reset(body: ResetIn, db: Session = Depends(get_db)):
    bad = HTTPException(400, "인증 코드가 맞지 않거나 만료되었습니다. 코드를 다시 받으세요")
    u = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    row = db.get(PasswordReset, u.id) if u is not None else None
    if row is None or row.expires_at < time.time() or row.attempts >= RESET_MAX_ATTEMPTS:
        raise bad
    if not hmac.compare_digest(row.code_hash, _code_hash(u.id, body.code.strip())):
        row.attempts += 1
        db.commit()
        left = RESET_MAX_ATTEMPTS - row.attempts
        raise HTTPException(400, f"인증 코드가 맞지 않습니다 (남은 횟수 {left}회)") if left > 0 else bad
    u.password_hash = hash_password(body.password)
    db.delete(row)
    db.commit()
    return {"token": make_token(u.id), "user": user_out(u)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)
