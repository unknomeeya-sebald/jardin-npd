"""NPD 정본 엑셀 → 엔진 테이블 변환기(app.tools.import_npd)"""
import io
import os
import tempfile
from datetime import date, datetime

# app 을 불러오기 전에 임시 SQLite로 고정 (실제 DB에 붙지 않도록)
os.environ.setdefault("DB_FORCE_SQLITE", "1")
os.environ.setdefault("SQLITE_PATH", os.path.join(tempfile.mkdtemp(), "test_import_npd.db"))

import openpyxl  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine, func, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import Base, ensure_columns  # noqa: E402
from app.models import Actual, DataQuality, Holiday, Product, Task, TaskCombo  # noqa: E402
from app.tools.import_npd import load, parse, summary  # noqa: E402

TP = ("NEW|표준", "기획세트|QUICK")


def _workbook(link_task="입점 제안", new_step="입점 제안\n(시제 · 목업)") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "NEW"
    ws.append([])
    ws.append(["연구원", "마케팅", "CAT", "품목", "제조사", "유형", "프로세스", "출시예상일", "구분",
               "컨셉 확정", new_step, "원·부자재 입고", "본생산", "비고 · 이슈"])
    d = datetime
    ws.append(["홍길동", "김철수", "조제", "제품\n가", "자사", "NEW", "표준", d(2027, 3, 5), "표준",
               d(2026, 10, 6), d(2026, 11, 27), d(2027, 2, 10), d(2027, 2, 17), "⚠ 본생산 2월 중순"])
    ws.append([None, None, None, None, None, None, None, None, "진행사항",
               "●", "1차 : 11/30", d(2027, 2, 23), "2월 중순"])
    ws.append(["홍길동", "김철수", "조제", "제품 나", "OEM", "기획세트", "QUICK", d(2027, 1, 14), "표준",
               "-", d(2026, 12, 4), d(2026, 12, 2), d(2026, 12, 29), None])
    ws.append([None, None, None, None, None, None, None, None, "진행사항", "●", 46328, "-", None])
    ws.append(["홍길동", "김철수", "조제", "출시일 없는 제품", "자사", "NEW", "표준", "미정", "표준"])
    ws.append([None, None, None, None, None, None, None, None, "표준"])  # 빈 양식 줄
    ws.append([None, None, None, None, None, None, None, None, "진행사항"])

    ws = wb.create_sheet("역산 계산기")
    ws.append(["역산 계산기"])
    ws.append([None, "No", "담당부서", "Task", "기준", "소요"])
    for no, dept, name in [(1, "마케팅", "컨셉 확정"), (2, "영업", "입점 제안"), (3, "구매", "원자재 발주·입고"),
                           (4, "구매", "부자재 발주·입고"), (5, "생산", "세트 구성품 생산"), (6, "구매·생산", "본생산")]:
        ws.append([None, no, dept, name])
    ws.append([])
    ws.append([None, "No", None, "Task", "후행 Task 1", "후행 Task 2", "고정 완료(D-영업일)", *TP, *TP, None, "공휴일"])
    ws.append([None, 1, None, "컨셉 확정", "입점 제안", "원자재 발주·입고", None, 60, 30, 5, 2, None, d(2027, 1, 1)])
    ws.append([None, 2, None, "입점 제안", "본생산", None, 15, 40, 20, 15, 2, None, d(2027, 2, 8)])
    ws.append([None, 3, None, "원자재 발주·입고", "세트 구성품 생산", "본생산", None, 30, 12, 20, 0, None, d(2028, 1, 26)])
    ws.append([None, 4, None, "부자재 발주·입고", "본생산", None, None, 25, 15, 15, 7])
    ws.append([None, 5, None, "세트 구성품 생산", "본생산", None, None, 0, 8, 0, 3])
    ws.append([None, 6, None, "본생산", None, None, None, 10, 5, 5, 2])

    ws = wb.create_sheet("기준일정")
    ws.append([])
    ws.append([None, "유형|프로세스", "컨셉 확정", "입점 제안", "원자재 발주·입고", "부자재 발주·입고", "본생산"])
    ws.append([None, "NEW|표준", 141, 87, 16, 16, 11])
    ws.append([])
    ws.append([None, "연결 Task (역산 계산기)", "컨셉 확정", link_task, "원자재 발주·입고", "부자재 발주·입고", "본생산"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture()
def parsed():
    return parse(_workbook())


def test_tasks_predecessors_fixed_and_combos(parsed):
    t = {x["no"]: x for x in parsed["tasks"]}
    assert len(t) == 6 and t[1]["dept"] == "마케팅" and t[6]["dept"] == "구매·생산"
    # 후행을 뒤집어 선행으로
    assert [t[n]["predecessors"] for n in range(1, 7)] == [[], [1], [1], [], [3], [2, 3, 4, 5]]
    assert t[2]["fixed_end"] == 15 and t[1]["fixed_end"] is None
    assert [t[n]["input_source"] for n in range(1, 7)] == ["엑셀", "엑셀", "엑셀", "엑셀", "없음", "엑셀"]
    assert parsed["excel_tasks"] == [1, 2, 3, 4, 6]
    assert len(parsed["combos"]) == 12
    c = {(x["task_no"], x["type_process"]): (x["start_offset"], x["duration"]) for x in parsed["combos"]}
    assert c[(1, "NEW|표준")] == (60, 5) and c[(1, "기획세트|QUICK")] == (30, 2)
    assert c[(5, "NEW|표준")] == (0, 0)  # 소요 0 = 그 조합에서 생략(행은 남긴다)
    assert parsed["holidays"] == [date(2027, 1, 1), date(2027, 2, 8), date(2028, 1, 26)]


def test_products_without_person_names(parsed):
    assert [p["name"] for p in parsed["products"]] == ["제품 가", "제품 나"]
    a = parsed["products"][0]
    assert (a["launch_date"], a["product_type"], a["process"]) == (date(2027, 3, 5), "NEW", "표준")
    assert (a["source_sheet"], a["excel_row"], a["cat"], a["maker"]) == ("NEW", 3, "조제", "자사")
    assert a["memo"].startswith("⚠")
    assert "홍길동" not in repr(parsed) and "김철수" not in repr(parsed)


def test_status_cells(parsed):
    got = {(a["product"], a["task_no"]): (a["state"], a["actual_end"], a["change_date"], a["estimated"])
           for a in parsed["actuals"]}
    assert got == {
        ("제품 가", 1): ("완료", date(2026, 10, 6), None, True),          # ● → 계획일로 추정
        ("제품 가", 3): ("예정변경", None, date(2027, 2, 23), None),      # 원·부자재 입고 한 칸 → Task 3·4
        ("제품 가", 4): ("예정변경", None, date(2027, 2, 23), None),
        ("제품 나", 1): ("완료", None, None, True),                        # ● 인데 계획일이 「-」
        ("제품 나", 3): ("해당없음", None, None, None),
        ("제품 나", 4): ("해당없음", None, None, None),
    }
    q = {(x["cell"], x["raw"]): x["reason"] for x in parsed["quality"]}
    assert set(q) == {("K4", "1차 : 11/30"), ("M4", "2월 중순"), ("J6", "●"), ("K6", "46328"), ("H7", "미정")}
    assert "날짜 서식이 아닌 숫자" in q[("K6", "46328")]
    assert "제품을 가져오지 않음" in q[("H7", "미정")]
    assert summary(parsed)["진행 실적"] == 6


def test_bad_link_task_is_error():
    with pytest.raises(ValueError, match="연결 Task 「없는 Task」"):
        parse(_workbook(link_task="없는 Task"))


def test_unlinked_step_goes_to_quality():
    p = parse(_workbook(new_step="새 단계"))
    assert any(q["raw"] == "새 단계" and "연결 Task에 없는 단계" in q["reason"] for q in p["quality"])
    assert not any(a["task_no"] == 2 for a in p["actuals"])


def test_missing_sheet_is_error():
    wb = openpyxl.Workbook()
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ValueError, match="역산 계산기"):
        parse(buf.getvalue())


def test_load_replaces_and_is_repeatable(parsed):
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as db:
        db.add_all([Task(no=13, name="입점 제안", basis="착수", start_offset=1, duration=1),
                    Product(name="제품A", launch_date=date(2027, 3, 26)),
                    Product(name="제품 가", launch_date=date(2027, 1, 1)),
                    Holiday(date=date(2027, 1, 1), name="신정")])
        db.flush()
        db.add(Actual(product_id=1, task_no=13, actual_end=date(2026, 1, 1)))
        db.commit()
        for _ in range(2):
            counts = load(db, parsed)
        assert counts["npd_tasks"] == 6 and counts["npd_products(새로 만든)"] == 0
        n = lambda M: db.scalar(select(func.count()).select_from(M))  # noqa: E731
        assert (n(Task), n(TaskCombo), n(Actual), n(DataQuality), n(Product), n(Holiday)) == (6, 12, 6, 5, 3, 3)
        t = {x.no: x for x in db.scalars(select(Task))}
        assert t[2].basis == "착수" and t[1].basis == "완료"  # 같은 이름의 기존 기준을 이어받음
        assert (t[1].start_offset, t[1].duration, t[6].predecessors) == (60, 5, "2,3,4,5")
        assert (t[5].start_offset, t[5].duration) == (None, None)  # NEW|표준에서 생략
        assert (t[1].input_source, t[5].input_source) == ("엑셀", "없음")
        p = db.scalar(select(Product).where(Product.name == "제품 가"))
        assert p.launch_date == date(2027, 3, 5) and p.excel_row == 3  # 이름이 같으면 고침
        assert db.get(Holiday, date(2027, 1, 1)).name == "신정"  # 있는 공휴일은 그대로


def test_ensure_columns_adds_missing_columns():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("create table npd_actuals (id integer primary key, product_id integer, task_no integer, actual_end date)"))
    added = ensure_columns(eng)
    assert {"npd_actuals.state", "npd_actuals.change_date", "npd_actuals.estimated", "npd_actuals.memo"} == set(added)
    assert ensure_columns(eng) == []
