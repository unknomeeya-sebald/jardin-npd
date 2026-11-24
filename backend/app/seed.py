"""CSV → DB. 비어 있을 때만 넣는다(기준 데이터는 덮어쓰지 않음)."""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Holiday, Product, Setting, Task

DATA = Path(__file__).resolve().parent.parent / "data"

DEFAULT_SETTINGS = {
    "yellow_threshold": ("3", "노랑 기준값(영업일). 예시 값 — 훈련에서 정함"),
    "absorb_limit_task": ("17", "흡수 한도 Task 번호(시제품 수령 전 구간 끝). 예시 값 — 확인 필요"),
}


def _int(v: str) -> int | None:
    v = (v or "").strip()
    return int(v) if v else None


# 화면 표의 한글 제목으로 적은 파일도 받는다
HEADER_ALIASES = {
    "no": "no", "번호": "no",
    "name": "name", "task": "name", "task명": "name", "업무": "name",
    "phase": "phase", "단계": "phase",
    "start_offset": "start_offset", "착수 역산": "start_offset", "착수역산": "start_offset", "착수 역산일수": "start_offset",
    "duration": "duration", "소요": "duration", "소요일수": "duration",
    "basis": "basis", "기준": "basis",
    "predecessors": "predecessors", "선행": "predecessors",
    "buffer_days": "buffer_days", "버퍼": "buffer_days", "여유": "buffer_days",
    "note": "note", "비고": "note",
}


def _cell(v) -> str:
    """엑셀 셀 값을 CSV와 같은 문자열로 바꾼다(159.0 → '159')."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _normalize(header: list, body: list[list]) -> list[dict]:
    keys = [HEADER_ALIASES.get(_cell(h).lower()) for h in header]
    missing = {"no", "name"} - set(keys)
    if missing:
        raise ValueError(f"첫 줄에 열 제목이 없습니다: {', '.join(sorted(missing))} (필수 열: no, name)")
    rows = []
    for line in body:
        r = {k: _cell(v) for k, v in zip(keys, line) if k}
        if any(r.values()):  # 빈 줄은 건너뜀
            rows.append(r)
    if not rows:
        raise ValueError("데이터 행이 없습니다")
    return rows


DEFAULT_TYPE_PROCESS = "NEW|표준"
_TP_RE = re.compile(r"^[^|\s]+\|[^|\s]+$")  # "NEW|표준" 같은 유형|프로세스 제목


def _calc_sheet_rows(lines: list[list], type_process: str) -> list[dict] | None:
    """정본 엑셀 「역산 계산기」 시트의 기준표(No·Task·후행 Task·유형|프로세스별 착수 역산·소요)를 읽는다.

    그런 표가 없는 시트면 None. 표 구조:
      제목 줄: No | Task | 후행 Task 1 | 후행 Task 2 | … | 유형|프로세스 × N (착수 역산 영업일) | 같은 제목 × N (소요 영업일)
    - 소요가 0인 Task는 그 유형에서 생략하는 Task라 가져오지 않는다(엑셀도 「-」로 표시).
    - 선행(predecessors)은 「후행 Task」를 뒤집어 만든다.
    - 위쪽 일정표(No·담당부서·Task·기준)가 있으면 담당부서는 비고에, 기준은 basis에 넣는다.
    """
    def cell(r: list, j: int | None):
        return r[j] if j is not None and j < len(r) else None

    h = next((i for i, r in enumerate(lines) if any(_cell(v) == "후행 Task 1" for v in r)), None)
    if h is None:
        return None
    head = [_cell(v) for v in lines[h]]
    try:
        c_no, c_name = head.index("No"), head.index("Task")
    except ValueError:
        raise ValueError("「역산 계산기」 기준표에 No·Task 열 제목이 없습니다") from None
    c_succ = [j for j, v in enumerate(head) if v.startswith("후행 Task")]
    tp_cols: dict[str, list[int]] = {}
    for j, v in enumerate(head):
        if _TP_RE.match(v):
            tp_cols.setdefault(v, []).append(j)
    if type_process not in tp_cols or len(tp_cols[type_process]) < 2:
        raise ValueError(f"「역산 계산기」 기준표에 {type_process} 열(착수 역산·소요)이 없습니다. "
                         f"있는 유형|프로세스: {', '.join(tp_cols) or '없음'}")
    c_start, c_dur = tp_cols[type_process][:2]

    # 위쪽 일정표: No | 담당부서 | Task | 기준 | …
    dept: dict[int, str] = {}
    basis: dict[int, str] = {}
    t = next((i for i, r in enumerate(lines[:h]) if "담당부서" in [_cell(v) for v in r]), None)
    if t is not None:
        th = [_cell(v) for v in lines[t]]
        if "No" in th:
            for r in lines[t + 1:h]:
                no = cell(r, th.index("No"))
                if isinstance(no, (int, float)):
                    dept[int(no)] = _cell(cell(r, th.index("담당부서")))
                    if "기준" in th:
                        basis[int(no)] = _cell(cell(r, th.index("기준")))

    def num(v, what: str, no: int) -> int:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or v < 0:
            raise ValueError(f"Task {no}의 {what} 값이 0 이상의 정수가 아닙니다: {v!r}")
        return int(v)

    tasks = []
    for r in lines[h + 1:]:
        no, name = cell(r, c_no), _cell(cell(r, c_name))
        if not isinstance(no, (int, float)) or isinstance(no, bool) or not name:
            if tasks:
                break  # 표 끝
            continue
        no = int(no)
        tasks.append(dict(no=no, name=name, start=num(cell(r, c_start), "착수 역산", no),
                          dur=num(cell(r, c_dur), "소요", no),
                          succ=[s for s in (_cell(cell(r, j)) for j in c_succ) if s]))
    if not tasks:
        raise ValueError("「역산 계산기」 기준표에 Task 행이 없습니다")

    kept = [t for t in tasks if t["dur"] > 0]
    no_by_name = {t["name"]: t["no"] for t in kept}
    all_names = {t["name"] for t in tasks}
    preds: dict[int, list[int]] = {}
    for t in kept:
        for s in t["succ"]:
            if s not in all_names:
                raise ValueError(f"Task {t['no']}의 후행 Task 「{s}」가 Task 목록에 없습니다")
            if s in no_by_name:  # 생략된 Task로 가는 연결은 뺀다
                preds.setdefault(no_by_name[s], []).append(t["no"])
    return [{
        "no": str(t["no"]), "name": t["name"], "phase": "",
        "start_offset": str(t["start"]), "duration": str(t["dur"]),
        "basis": basis.get(t["no"], ""),
        "predecessors": ",".join(str(p) for p in sorted(preds.get(t["no"], []))),
        "buffer_days": "",
        "note": f"{type_process} 기준" + (f" · 담당 {dept[t['no']]}" if dept.get(t["no"]) else ""),
    } for t in kept]


def rows_from_upload(filename: str, data: bytes, type_process: str = DEFAULT_TYPE_PROCESS) -> list[dict]:
    """올린 파일(CSV 또는 엑셀 .xlsx)을 Task 행 dict 목록으로 읽는다. 형식이 틀리면 ValueError.

    엑셀은 ① 정본 통합 파일(「역산 계산기」 시트의 type_process 열) ② 첫 줄이 열 제목인 단순 표 둘 다 받는다.
    """
    ext = Path(filename or "").suffix.lower()
    if ext == ".xls":
        raise ValueError("옛 엑셀 형식(.xls)은 읽을 수 없습니다. 엑셀에서 .xlsx로 저장해 올리세요")
    if ext in (".xlsx", ".xlsm") or data[:4] == b"PK\x03\x04":
        import openpyxl

        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"엑셀 파일을 열 수 없습니다: {e}") from e
        sheets = [[list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets]
        # 정본 통합 엑셀(「역산 계산기」 시트)이면 그 시트의 기준표를 읽는다
        for lines in sheets:
            rows = _calc_sheet_rows(lines, type_process)
            if rows is not None:
                return rows
        # 아니면 필수 열 제목이 첫 줄에 있는 첫 번째 시트를 쓴다
        err: ValueError | None = None
        for lines in sheets:
            if not lines:
                continue
            try:
                return _normalize(lines[0], lines[1:])
            except ValueError as e:
                err = err or e
        raise err or ValueError("빈 엑셀 파일입니다")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp949")  # 한글 엑셀의 「CSV(쉼표로 분리)」 저장
    lines = list(csv.reader(io.StringIO(text)))
    if not lines:
        raise ValueError("빈 파일입니다")
    return _normalize(lines[0], lines[1:])


def parse_task_rows(rows: list[dict]) -> list[Task]:
    out = []
    for r in rows:
        out.append(Task(
            no=int(r["no"]), name=r["name"].strip(), phase=(r.get("phase") or "").strip() or None,
            start_offset=_int(r.get("start_offset", "")), duration=_int(r.get("duration", "")),
            basis=(r.get("basis") or "완료").strip() or "완료",
            predecessors=(r.get("predecessors") or "").strip() or None,
            buffer_days=_int(r.get("buffer_days", "")), note=(r.get("note") or "").strip() or None,
        ))
    return out


def seed(db: Session) -> None:
    if db.scalar(select(Task).limit(1)) is None:
        with open(DATA / "tasks_seed.csv", encoding="utf-8") as f:
            db.add_all(parse_task_rows(list(csv.DictReader(f))))
    if db.scalar(select(Holiday).limit(1)) is None:
        with open(DATA / "holidays.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                db.add(Holiday(date=date.fromisoformat(r["date"]), name=r["name"],
                               kind=r["kind"] or "공휴일", note=r.get("note") or None))
    for k, (v, note) in DEFAULT_SETTINGS.items():
        if db.get(Setting, k) is None:
            db.add(Setting(key=k, value=v, note=note))
    if db.scalar(select(Product).limit(1)) is None:
        db.add_all([
            Product(name="제품A", launch_date=date(2027, 3, 26), product_type="NEW", process="표준"),
            Product(name="제품B", launch_date=date(2027, 4, 23), product_type="NEW", process="표준"),
        ])
    db.commit()
