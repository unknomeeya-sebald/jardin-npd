"""CSV → DB. 비어 있을 때만 넣는다(기준 데이터는 덮어쓰지 않음)."""
from __future__ import annotations

import csv
import io
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


def rows_from_upload(filename: str, data: bytes) -> list[dict]:
    """올린 파일(CSV 또는 엑셀 .xlsx)을 Task 행 dict 목록으로 읽는다. 형식이 틀리면 ValueError."""
    ext = Path(filename or "").suffix.lower()
    if ext == ".xls":
        raise ValueError("옛 엑셀 형식(.xls)은 읽을 수 없습니다. 엑셀에서 .xlsx로 저장해 올리세요")
    if ext in (".xlsx", ".xlsm") or data[:4] == b"PK\x03\x04":
        import openpyxl

        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"엑셀 파일을 열 수 없습니다: {e}") from e
        # 필수 열 제목이 첫 줄에 있는 첫 번째 시트를 쓴다
        err: ValueError | None = None
        for ws in wb.worksheets:
            lines = [list(r) for r in ws.iter_rows(values_only=True)]
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
