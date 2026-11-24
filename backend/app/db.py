"""DB 연결. Supabase(Postgres)에 붙고, 실패하면 로컬 SQLite로 대체한다(/api/health에 표시)."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
log = logging.getLogger("npd.db")


class Base(DeclarativeBase):
    pass


def _pg_url() -> URL | None:
    if not os.getenv("DB_HOST"):
        return None
    return URL.create(
        "postgresql+psycopg",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "postgres"),
    )


def _make_engine():
    if os.getenv("DB_FORCE_SQLITE") != "1":
        url = _pg_url()
        if url is not None:
            try:
                eng = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
                with eng.connect() as c:
                    c.execute(text("select 1"))
                return eng, "postgres"
            except Exception as e:  # noqa: BLE001
                log.warning("Postgres 연결 실패, SQLite로 대체: %s", str(e).splitlines()[0])
    path = os.getenv("SQLITE_PATH", str(BASE_DIR / "local.db"))
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False}), "sqlite"


engine, DB_KIND = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def ensure_columns(eng=None) -> list[str]:
    """모델에 새로 생긴 칸을 이미 있는 테이블에 더한다(create_all은 새 테이블만 만든다).

    더하기만 하고 지우거나 바꾸지 않는다. 더한 칸 이름("표.칸") 목록을 돌려준다.
    """
    eng = eng or engine
    insp = inspect(eng)
    added = []
    with eng.begin() as c:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {col["name"] for col in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    if not col.nullable:
                        raise RuntimeError(f"{table.name}.{col.name}: 빈 값을 허용하지 않는 칸은 자동으로 더할 수 없습니다")
                    c.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(eng.dialect)}'))
                    added.append(f"{table.name}.{col.name}")
    if added:
        log.info("칸 추가: %s", ", ".join(added))
    return added


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
