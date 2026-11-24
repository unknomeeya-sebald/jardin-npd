"""Task 기준 가져오기: CSV와 엑셀(.xlsx) 모두 받는다."""
import io
import os
import tempfile

# app 을 불러오기 전에 임시 SQLite로 고정 (실제 DB를 바꾸지 않도록)
os.environ["DB_FORCE_SQLITE"] = "1"
os.environ["SQLITE_PATH"] = os.path.join(tempfile.mkdtemp(), "test_task_import.db")

import openpyxl  # noqa: E402
import pytest  # noqa: E402

from app.seed import parse_task_rows, rows_from_upload  # noqa: E402

HEAD = ["no", "name", "phase", "start_offset", "duration", "basis", "predecessors", "buffer_days", "note"]


def _xlsx(rows: list[list], title: str = "Sheet1", extra_first_sheet: bool = False) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    if extra_first_sheet:
        ws.title = "설명"
        ws.append(["이 파일은 Task 기준입니다"])
        ws = wb.create_sheet(title)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_matches_csv():
    csv_bytes = ("no,name,phase,start_offset,duration,basis,predecessors,buffer_days,note\n"
                 "2,컨셉 확정,기획,159,5,완료,,,메모\n"
                 "3,디자인 의뢰,,154,1,착수,2,2,\n").encode("utf-8")
    xlsx_bytes = _xlsx([HEAD,
                        [2, "컨셉 확정", "기획", 159.0, 5, "완료", None, None, "메모"],
                        [3, "디자인 의뢰", None, 154, 1, "착수", 2, 2, None],
                        [None] * 9])  # 빈 줄은 건너뜀
    a = rows_from_upload("tasks.csv", csv_bytes)
    b = rows_from_upload("tasks.xlsx", xlsx_bytes)
    assert a == b
    tasks = parse_task_rows(b)
    assert [(t.no, t.name, t.start_offset, t.duration, t.basis, t.predecessors, t.buffer_days) for t in tasks] == [
        (2, "컨셉 확정", 159, 5, "완료", None, None), (3, "디자인 의뢰", 154, 1, "착수", "2", 2)]


def test_korean_headers_and_second_sheet():
    data = _xlsx([["No", "Task", "단계", "착수 역산", "소요", "기준", "선행", "비고"],
                  [10, "관능평가", "개발", 138, 45, "완료", "4,5", "확인"]], extra_first_sheet=True)
    (t,) = parse_task_rows(rows_from_upload("기준.xlsx", data))
    assert (t.no, t.name, t.phase, t.start_offset, t.duration, t.predecessors, t.note) == (10, "관능평가", "개발", 138, 45, "4,5", "확인")


def test_cp949_csv():
    data = "no,name\n1,컨셉 확정\n".encode("cp949")
    assert rows_from_upload("a.csv", data) == [{"no": "1", "name": "컨셉 확정"}]


@pytest.mark.parametrize("name,data", [
    ("old.xls", b"\xd0\xcf\x11\xe0"),
    ("bad.xlsx", b"not an excel file"),
    ("nohead.xlsx", None),
    ("empty.csv", b""),
])
def test_bad_files_raise_value_error(name, data):
    if data is None:
        data = _xlsx([["이름", "값"], ["a", 1]])
    with pytest.raises(ValueError):
        rows_from_upload(name, data)


def test_import_api_accepts_xlsx_and_rejects_duplicates():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    r = client.post("/api/auth/signup", json={"email": "import-test@jardin.co.kr", "name": "테스트", "password": "test1234"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    before = len(client.get("/api/tasks", headers=h).json())

    dup = _xlsx([HEAD[:2], [1, "가"], [1, "나"]])
    r = client.post("/api/tasks/import", headers=h, files={"file": ("dup.xlsx", dup)})
    assert r.status_code == 400
    assert len(client.get("/api/tasks", headers=h).json()) == before  # 실패하면 기존 데이터 유지

    ok = _xlsx([HEAD, [1, "가", None, 10, 2, "완료", None, None, None], [2, "나", None, 8, 3, "착수", 1, None, None]])
    r = client.post("/api/tasks/import", headers=h, files={"file": ("ok.xlsx", ok)})
    assert r.status_code == 200 and r.json() == {"imported": 2}
    assert [t["name"] for t in client.get("/api/tasks", headers=h).json()] == ["가", "나"]


# ---------- 정본 통합 엑셀(「역산 계산기」 시트) ----------
def _calc_workbook(tp_head=("NEW|표준", "NEW|QUICK")) -> bytes:
    wb = openpyxl.Workbook()
    wb.active.title = "NEW"
    wb.active.append(["연구원", "마케팅", "품목"])  # 제품 일정 시트(Task 기준 아님)
    ws = wb.create_sheet("역산 계산기")
    ws.append(["역산 계산기"])
    ws.append([None, "No", "담당부서", "Task", "기준", "소요"])
    ws.append([None, 1, "마케팅", "컨셉 확정", None, "5일"])
    ws.append([None, 2, "영업", "입점 제안", "착수", "15일"])
    ws.append([None, 3, "생산", "세트 생산", None, "-"])
    ws.append([None, 4, "마케팅", "출시", None, "1일"])
    ws.append([])
    ws.append([None, "No", None, "Task", "후행 Task 1", "후행 Task 2", *tp_head, *tp_head])
    ws.append([None, 1, None, "컨셉 확정", "입점 제안", "세트 생산", 30, 20, 5, 2])
    ws.append([None, 2, None, "입점 제안", "출시", None, 25.0, 18, 15, 10])
    ws.append([None, 3, None, "세트 생산", "출시", None, 0, 9, 0, 4])
    ws.append([None, 4, None, "출시", None, None, 1, 1, 1, 1])
    ws.append([])
    ws.append([None, "[수식 설계] 설명 줄"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_calc_sheet_default_type_process():
    rows = rows_from_upload("NPD_교정.xlsx", _calc_workbook())
    got = [(t.no, t.name, t.start_offset, t.duration, t.basis, t.predecessors, t.note) for t in parse_task_rows(rows)]
    assert got == [
        (1, "컨셉 확정", 30, 5, "완료", None, "NEW|표준 기준 · 담당 마케팅"),
        (2, "입점 제안", 25, 15, "착수", "1", "NEW|표준 기준 · 담당 영업"),
        # 3 세트 생산: 소요 0 → 이 유형에서 생략
        (4, "출시", 1, 1, "완료", "2", "NEW|표준 기준 · 담당 마케팅"),
    ]


def test_calc_sheet_other_type_process_keeps_task_3():
    rows = rows_from_upload("a.xlsx", _calc_workbook(), "NEW|QUICK")
    got = [(t.no, t.start_offset, t.duration, t.predecessors) for t in parse_task_rows(rows)]
    assert got == [(1, 20, 2, None), (2, 18, 10, "1"), (3, 9, 4, "1"), (4, 1, 1, "2,3")]


def test_calc_sheet_missing_type_process_is_error():
    with pytest.raises(ValueError, match=r"NEW\|표준 열"):
        rows_from_upload("a.xlsx", _calc_workbook(tp_head=("리뉴얼|표준", "리뉴얼|QUICK")))


def test_import_api_inherits_basis_by_name():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    r = client.post("/api/auth/signup", json={"email": "import-test2@jardin.co.kr", "name": "테스트", "password": "test1234"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    first = _xlsx([HEAD[:2] + ["basis"], [7, "입점 제안", "착수"], [8, "출시", None]])
    assert client.post("/api/tasks/import", headers=h, files={"file": ("a.xlsx", first)}).status_code == 200
    # 기준 열이 없는 파일을 올려도 같은 이름 Task의 「착수」가 유지된다
    second = _xlsx([HEAD[:2], [2, "입점 제안"], [9, "출시"]])
    assert client.post("/api/tasks/import", headers=h, files={"file": ("b.xlsx", second)}).status_code == 200
    assert {t["name"]: t["basis"] for t in client.get("/api/tasks", headers=h).json()} == {"입점 제안": "착수", "출시": "완료"}
