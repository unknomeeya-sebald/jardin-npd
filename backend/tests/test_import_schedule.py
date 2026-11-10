"""일정관리 내장 데이터 → npd_sched_* 가져오기"""
import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import Base
from app.sched_models import SchedMeta, SchedProduct, SchedProductStep, SchedSheet, SchedStdDays, SchedTask
from app.tools.import_schedule import HTML, load, parse

pytestmark = pytest.mark.skipif(not HTML.is_file(), reason="일정관리 원본 파일 없음")


@pytest.fixture(scope="module")
def parsed():
    return parse()


def test_parse_counts(parsed):
    assert len(parsed["tasks"]) == 39
    assert len(parsed["nodes"]) == 53 and len(parsed["edges"]) == 58
    sheets = {s["name"] for s in parsed["sheets"]}
    assert {"NEW", "표기수정", "역산 계산기", "기준일정"} <= sheets
    # 그 아래는 「표준·진행사항」 머리표만 있는 빈 양식 줄이라 제품이 아니다
    assert sum(p["sheet"] == "NEW" for p in parsed["products"]) == 8
    assert sum(p["sheet"] == "표기수정" for p in parsed["products"]) == 6
    assert len(parsed["std"]) == 8 * 16


def test_new_product_row_and_status(parsed):
    p = next(p for p in parsed["products"] if p["sheet"] == "NEW")
    assert p["name"].startswith("아워티_ZERO_3종")
    assert p["product_type"] == "리뉴얼" and p["process"] == "QUICK"
    assert p["launch_date"].isoformat() == "2026-11-20"
    concept = next(s for s in p["steps"] if s["step"] == "컨셉 확정")
    assert concept["plan_date"].isoformat() == "2026-07-21"
    assert concept["status_text"] == "●"
    assert concept["dept"] == "마케팅"


def test_load_is_idempotent(parsed):
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as db:
        c1 = load(db, parsed)
        c2 = load(db, parsed)  # 다시 넣어도 건수 같음
        assert c1 == c2
        assert db.scalar(select(func.count()).select_from(SchedTask)) == 39
        assert db.scalar(select(func.count()).select_from(SchedProduct)) == c1["npd_sched_products"]
        assert db.scalar(select(func.count()).select_from(SchedProductStep)) == c1["npd_sched_product_steps"]
        assert db.scalar(select(func.count()).select_from(SchedStdDays)) == 128
        rows = json.loads(db.get(SchedSheet, "역산 계산기").rows_json)
        assert any("역산 계산기" in [c for c in r if isinstance(c, str)] for r in rows)
        assert db.get(SchedMeta, "canon_xlsx_b64").value.startswith("UEsDB")
