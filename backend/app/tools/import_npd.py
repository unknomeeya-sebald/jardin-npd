"""NPD 정본 엑셀 → 간트·신호등 엔진 테이블(npd_tasks·npd_task_combo·npd_products·npd_actuals …).

    python -m app.tools.import_npd 파일.xlsx                       # 읽고 건수만 보여 줌(DB는 안 바꿈)
    python -m app.tools.import_npd 파일.xlsx --apply               # .env 의 Postgres(Supabase)에 넣음
    python -m app.tools.import_npd 파일.xlsx --apply --allow-sqlite  # Postgres 연결이 안 되면 로컬 SQLite에 넣음

읽는 곳 → 넣는 곳
- 「역산 계산기」 Task 39개 이름·담당부서        → npd_tasks 전면 교체(name, dept)
- 「역산 계산기」 후행 Task 1·2                  → npd_tasks.predecessors (뒤집어 선행으로)
- 「역산 계산기」 고정 완료(D-영업일)            → npd_tasks.fixed_end
- 「역산 계산기」 유형|프로세스별 착수 역산·소요 → npd_task_combo (소요 0 = 그 조합에서 생략)
- 「역산 계산기」 공휴일 열                      → npd_holidays (없는 날짜만 더함)
- 「NEW」 제품 행(구분 = 표준)                   → npd_products (이름이 같으면 고침)
- 「NEW」 「진행사항」 행                        → npd_actuals. 「기준일정」의 「연결 Task (역산 계산기)」 행으로 Task에 연결
- 해석하지 못한 칸                               → npd_data_quality (시트·칸·원문·사유)
- Task 입력 원천                                 → npd_tasks.input_source: NEW 시트에 칸이 있는 Task·출시 = 엑셀,
  칸 없는 디자인 Task = 디자인 시트, 그 외 = 없음. 엑셀이 아닌 Task는 입력이 들어오기 전까지 신호등 판정에서 뺀다

「진행사항」 칸 해석: ● = 완료(완료일은 같은 칸의 계획일로 추정) / 날짜 서식 칸 = 변경 예정일 /
- = 해당 없음 / 빈칸 = 계획대로 / 그 외 글·숫자 = 해석하지 않고 데이터 품질 목록에 남김.
「원·부자재 입고」 한 칸은 원자재 발주·입고, 부자재 발주·입고 두 Task에 같은 값으로 넣는다(2026-11-24 마케팅 결정).
연구원·마케팅 담당자 이름은 읽지 않는다.

주의: --apply 는 npd_tasks·npd_task_combo·npd_actuals·npd_data_quality 를 비우고 다시 채운다(기존 실적 삭제).
Task 번호 체계가 바뀌므로(34-Task → 39-Task) 옛 실적은 남겨도 엉뚱한 Task를 가리킨다.
"""
from __future__ import annotations

import io
import re
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Actual, DataQuality, Holiday, Product, Task, TaskCombo

SHEET_CALC, SHEET_STD, SHEET_NEW = "역산 계산기", "기준일정", "NEW"
DEFAULT_TP = "NEW|표준"  # npd_tasks 의 start_offset·duration 에 넣는 조합(조합 값이 없는 유형의 대비값)
DONE, CHANGED, NA = "완료", "예정변경", "해당없음"
SRC_EXCEL, SRC_DESIGN, SRC_NONE = "엑셀", "디자인 시트", "없음"
# 디자인 일정은 VC가 NPD_디자인일정 시트에 입력한다(재설계서). 엑셀 NEW 시트에 칸이 없는 디자인 Task만 해당
DESIGN_WORDS = ("디자인", "상세페이지", "인쇄파일")
LAUNCH_TASK = "출시"  # 출시일은 NEW 시트 「출시예상일」 칸으로 들어온다
# NEW 시트 한 칸이 기준일정의 두 단계에 해당하는 경우(2026-11-24 마케팅 결정)
STEP_ALIASES = {"원부자재입고": ["원자재 발주·입고", "부자재 발주·입고"]}
_TP_RE = re.compile(r"^[^|\s]+\|[^|\s]+$")


# ---------- 칸 값 ----------
def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _d(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def _norm(s: str) -> str:
    return re.sub(r"[\s·/]", "", s)


def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _addr(row: int, col: int) -> str:
    from openpyxl.utils import get_column_letter
    return f"{get_column_letter(col + 1)}{row + 1}"


def _get(r: list, j: int | None):
    return r[j] if j is not None and j < len(r) else None


def _find_row(rows: list[list], pred, what: str, sheet: str) -> int:
    for i, r in enumerate(rows):
        if any(pred(_s(v)) for v in r):
            return i
    raise ValueError(f"「{sheet}」 시트에서 {what} 줄을 찾지 못했습니다")


def _nonneg_int(v, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or v < 0:
        raise ValueError(f"「{SHEET_CALC}」 {what} 값이 0 이상의 정수가 아닙니다: {v!r}")
    return int(v)


# ---------- 역산 계산기 ----------
def _parse_calc(rows: list[list]) -> dict:
    h = _find_row(rows, lambda s: s == "후행 Task 1", "기준표 제목(후행 Task 1)", SHEET_CALC)
    head = [_s(v) for v in rows[h]]
    try:
        c_no, c_name = head.index("No"), head.index("Task")
    except ValueError:
        raise ValueError(f"「{SHEET_CALC}」 기준표에 No·Task 열 제목이 없습니다") from None
    c_succ = [j for j, v in enumerate(head) if v.startswith("후행 Task")]
    c_fixed = next((j for j, v in enumerate(head) if v.startswith("고정 완료")), None)
    c_holi = next((j for j, v in enumerate(head) if v == "공휴일"), None)
    tp_cols: dict[str, list[int]] = {}
    for j, v in enumerate(head):
        if _TP_RE.match(v):
            tp_cols.setdefault(v, []).append(j)
    bad = [tp for tp, cols in tp_cols.items() if len(cols) != 2]
    if not tp_cols or bad:
        raise ValueError(f"「{SHEET_CALC}」 기준표의 유형|프로세스 열은 착수 역산·소요로 두 번씩 있어야 합니다"
                         f"(문제: {', '.join(bad) or '열 없음'})")

    # 위쪽 일정표: No | 담당부서 | Task | …
    dept: dict[int, str] = {}
    t = next((i for i, r in enumerate(rows[:h]) if "담당부서" in [_s(v) for v in r]), None)
    if t is not None:
        th = [_s(v) for v in rows[t]]
        if "No" in th:
            for r in rows[t + 1:h]:
                no = _get(r, th.index("No"))
                if isinstance(no, (int, float)) and not isinstance(no, bool):
                    dept[int(no)] = _s(_get(r, th.index("담당부서")))

    tasks, combos = [], []
    for r in rows[h + 1:]:
        no, name = _get(r, c_no), _s(_get(r, c_name))
        if not isinstance(no, (int, float)) or isinstance(no, bool) or not name:
            if tasks:
                break  # 표 끝
            continue
        no = int(no)
        fixed = _get(r, c_fixed)
        tasks.append(dict(no=no, name=name, dept=dept.get(no) or None,
                          succ=[s for s in (_s(_get(r, j)) for j in c_succ) if s],
                          fixed_end=None if fixed in (None, "") else _nonneg_int(fixed, f"Task {no} 고정 완료")))
        for tp, (cs, cd) in tp_cols.items():
            combos.append(dict(task_no=no, type_process=tp,
                               start_offset=_nonneg_int(_get(r, cs), f"Task {no} {tp} 착수 역산"),
                               duration=_nonneg_int(_get(r, cd), f"Task {no} {tp} 소요")))
    if not tasks:
        raise ValueError(f"「{SHEET_CALC}」 기준표에 Task 행이 없습니다")
    if len({t["no"] for t in tasks}) != len(tasks) or len({t["name"] for t in tasks}) != len(tasks):
        raise ValueError(f"「{SHEET_CALC}」 기준표에 번호나 이름이 겹치는 Task가 있습니다")

    no_by_name = {t["name"]: t["no"] for t in tasks}
    preds: dict[int, list[int]] = {}
    for t in tasks:
        for s in t["succ"]:
            if s not in no_by_name:
                raise ValueError(f"Task {t['no']}의 후행 Task 「{s}」가 Task 목록에 없습니다")
            preds.setdefault(no_by_name[s], []).append(t["no"])
    for t in tasks:
        t["predecessors"] = sorted(set(preds.get(t["no"], [])))
        del t["succ"]

    holidays = sorted({d for d in (_d(_get(r, c_holi)) for r in rows[h + 1:]) if d}) if c_holi is not None else []
    return dict(tasks=tasks, combos=combos, holidays=holidays, type_processes=list(tp_cols))


# ---------- 기준일정: 단계 → 연결 Task ----------
def _parse_links(rows: list[list], no_by_name: dict[str, int]) -> dict[str, int]:
    """기준일정 단계 이름(정규화) → Task 번호"""
    h = _find_row(rows, lambda s: s == "유형|프로세스", "제목(유형|프로세스)", SHEET_STD)
    link = _find_row(rows, lambda s: s.startswith("연결 Task"), "「연결 Task (역산 계산기)」", SHEET_STD)
    c0 = next(j for j, v in enumerate(rows[h]) if _s(v) == "유형|프로세스")
    out = {}
    for j, v in enumerate(rows[h]):
        step, task = _s(v), _s(_get(rows[link], j))
        if j <= c0 or not step:
            continue
        if task not in no_by_name:
            raise ValueError(f"「{SHEET_STD}」 {_addr(link, j)}: 단계 「{step}」의 연결 Task 「{task}」가 "
                             f"「{SHEET_CALC}」 Task 목록에 없습니다")
        out[_norm(step)] = no_by_name[task]
    return out


def _step_tasks(header: str, links: dict[str, int]) -> list[int]:
    """NEW 시트 단계 제목 → Task 번호들. 제목 전체, 안 맞으면 첫 줄(괄호 설명 앞)로 맞춘다."""
    for cand in (_norm(header), _norm(header.split("\n")[0])):
        if cand in STEP_ALIASES:
            return [links[_norm(s)] for s in STEP_ALIASES[cand] if _norm(s) in links]
        if cand in links:
            return [links[cand]]
    return []


# ---------- NEW: 제품 + 진행사항 ----------
def _parse_new(rows: list[list], links: dict[str, int]) -> dict:
    h = _find_row(rows, lambda s: s == "품목", "제목(품목)", SHEET_NEW)
    head = {_one_line(_s(v)): j for j, v in enumerate(rows[h]) if _s(v)}
    need = ["품목", "유형", "프로세스", "출시예상일", "구분"]
    missing = [k for k in need if k not in head]
    if missing:
        raise ValueError(f"「{SHEET_NEW}」 시트에 열 제목이 없습니다: {', '.join(missing)}")
    c_note = next((j for k, j in head.items() if k.startswith("비고")), None)
    last = c_note if c_note is not None else len(rows[h])
    step_cols = [(j, _s(rows[h][j])) for j in range(head["구분"] + 1, last) if _s(rows[h][j])]

    quality: list[dict] = []
    q = lambda i, j, product, step, raw, reason: quality.append(  # noqa: E731
        dict(sheet=SHEET_NEW, cell=_addr(i, j), product=product, step=_one_line(step)[:100] if step else None,
             raw=raw, reason=reason))

    col_tasks = {}
    for j, title in step_cols:
        col_tasks[j] = _step_tasks(title, links)
        if not col_tasks[j]:
            q(h, j, None, title, title, f"「{SHEET_STD}」 연결 Task에 없는 단계 — 이 열은 가져오지 않음")

    products, actuals, names = [], [], set()
    i = h + 1
    while i < len(rows):
        r = rows[i]
        name, kind = _one_line(_s(_get(r, head["품목"]))), _s(_get(r, head["구분"]))
        if not name or kind == "진행사항":
            i += 1
            continue
        name = name[:100]
        if name in names:
            name = f"{name[:90]} (행 {i + 1})"
        launch = _d(_get(r, head["출시예상일"]))
        ptype, proc = _s(_get(r, head["유형"])), _s(_get(r, head["프로세스"]))
        status = rows[i + 1] if i + 1 < len(rows) and _s(_get(rows[i + 1], head["구분"])) == "진행사항" else None
        step = 2 if status is not None else 1
        if launch is None or not ptype or not proc:
            q(i, head["출시예상일"], name, None, _s(_get(r, head["출시예상일"])),
              "출시예상일(날짜)·유형·프로세스가 없어 제품을 가져오지 않음")
            i += step
            continue
        names.add(name)
        products.append(dict(name=name, launch_date=launch, product_type=ptype, process=proc,
                             source_sheet=SHEET_NEW, excel_row=i + 1,
                             cat=_s(_get(r, head.get("CAT"))) or None, maker=_s(_get(r, head.get("제조사"))) or None,
                             memo=_s(_get(r, c_note)) or None))
        if status is not None:
            for j, title in step_cols:
                v = _get(status, j)
                raw = _s(v)
                if not raw or not col_tasks[j]:
                    continue
                a = None
                if _d(v) is not None:
                    a = dict(state=CHANGED, change_date=_d(v))
                elif raw == "●":
                    plan = _d(_get(r, j))
                    a = dict(state=DONE, actual_end=plan, estimated=True)
                    if plan is None:
                        q(i + 1, j, name, title, raw, "완료(●)인데 같은 칸 계획일이 날짜가 아니라 완료일을 추정하지 못함")
                elif raw == "-":
                    a = dict(state=NA)
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    q(i + 1, j, name, title, raw, "날짜 서식이 아닌 숫자 — 계획일 유지")
                else:
                    q(i + 1, j, name, title, raw, "날짜·●·- 가 아닌 글 — 해석하지 않고 계획일 유지")
                if a is not None:
                    for no in col_tasks[j]:
                        actuals.append(dict(product=name, task_no=no, actual_end=None, change_date=None,
                                            estimated=None, memo=None) | a)
        i += step
    excel_tasks = sorted({no for nos in col_tasks.values() for no in nos})
    return dict(products=products, actuals=actuals, quality=quality, excel_tasks=excel_tasks)


# ---------- 읽기 ----------
def parse(src: Path | str | bytes) -> dict:
    """엑셀 파일(경로 또는 바이트)을 읽어 넣을 행들을 만든다. DB는 건드리지 않는다. 형식이 틀리면 ValueError."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(src) if isinstance(src, bytes) else src, data_only=True)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"엑셀 파일을 열 수 없습니다: {e}") from e
    sheets = {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    for name in (SHEET_CALC, SHEET_STD, SHEET_NEW):
        if name not in sheets:
            raise ValueError(f"「{name}」 시트가 없습니다(있는 시트: {', '.join(sheets)})")
    calc = _parse_calc(sheets[SHEET_CALC])
    links = _parse_links(sheets[SHEET_STD], {t["name"]: t["no"] for t in calc["tasks"]})
    p = calc | _parse_new(sheets[SHEET_NEW], links)
    for t in p["tasks"]:
        t["input_source"] = _input_source(t, set(p["excel_tasks"]))
    return p


def _input_source(t: dict, excel_tasks: set[int]) -> str:
    if t["no"] in excel_tasks or t["name"] == LAUNCH_TASK:
        return SRC_EXCEL
    if any(w in t["name"] for w in DESIGN_WORDS):
        return SRC_DESIGN
    return SRC_NONE


# ---------- 쓰기 ----------
def load(db: Session, p: dict) -> dict[str, int]:
    # 기준(완료·착수)은 엑셀에 없으므로 같은 이름의 기존 Task 값을 이어받는다(예: 입점 제안 = 착수)
    old_basis = {t.name: t.basis for t in db.scalars(select(Task))}
    for M in (Actual, DataQuality, TaskCombo, Task):
        db.execute(delete(M))
    default = {c["task_no"]: c for c in p["combos"] if c["type_process"] == DEFAULT_TP}
    for t in p["tasks"]:
        c = default.get(t["no"])
        keep = c is not None and c["duration"] > 0  # 소요 0(생략) → 값 비움 = 「확인 필요」
        db.add(Task(no=t["no"], name=t["name"], dept=t["dept"], fixed_end=t["fixed_end"],
                    input_source=t["input_source"],
                    predecessors=",".join(map(str, t["predecessors"])) or None,
                    start_offset=c["start_offset"] if keep else None, duration=c["duration"] if keep else None,
                    basis=old_basis.get(t["name"]) or "완료"))
    db.add_all(TaskCombo(**c) for c in p["combos"])

    by_name = {x.name: x for x in db.scalars(select(Product))}
    n_new = 0
    for pr in p["products"]:
        row = by_name.get(pr["name"])
        if row is None:
            row = by_name[pr["name"]] = Product(name=pr["name"])
            db.add(row)
            n_new += 1
        for k, v in pr.items():
            setattr(row, k, v)
    db.flush()
    db.add_all(Actual(product_id=by_name[a["product"]].id, **{k: v for k, v in a.items() if k != "product"})
               for a in p["actuals"])
    db.add_all(DataQuality(**q) for q in p["quality"])

    have = set(db.scalars(select(Holiday.date)))
    new_h = [d for d in p["holidays"] if d not in have]
    db.add_all(Holiday(date=d, name="공휴일", kind="공휴일", note=f"「{SHEET_CALC}」 공휴일 열") for d in new_h)
    db.commit()
    return {"npd_tasks": len(p["tasks"]), "npd_task_combo": len(p["combos"]),
            "npd_products": len(p["products"]), "npd_products(새로 만든)": n_new,
            "npd_actuals": len(p["actuals"]), "npd_data_quality": len(p["quality"]),
            "npd_holidays(더한)": len(new_h)}


def summary(p: dict) -> dict[str, int]:
    by = lambda s: sum(a["state"] == s for a in p["actuals"])  # noqa: E731
    return {"Task": len(p["tasks"]), "선행 연결": sum(len(t["predecessors"]) for t in p["tasks"]),
            "고정 완료 Task": sum(t["fixed_end"] is not None for t in p["tasks"]),
            "입력 원천 엑셀": sum(t["input_source"] == SRC_EXCEL for t in p["tasks"]),
            "입력 원천 디자인 시트": sum(t["input_source"] == SRC_DESIGN for t in p["tasks"]),
            "입력 원천 없음": sum(t["input_source"] == SRC_NONE for t in p["tasks"]),
            "유형|프로세스 조합": len(p["type_processes"]), "조합 값": len(p["combos"]),
            "제품": len(p["products"]), "진행 실적": len(p["actuals"]),
            "  완료(●)": by(DONE), "  변경 예정일": by(CHANGED), "  해당 없음(-)": by(NA),
            "읽지 못한 칸": len(p["quality"]), "공휴일(엑셀)": len(p["holidays"])}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    files = [a for a in argv if not a.startswith("--")]
    if len(files) != 1:
        print(__doc__)
        return 1
    try:
        p = parse(Path(files[0]))
    except ValueError as e:
        print(f"읽기 실패: {e}")
        return 1
    print(f"읽은 내용: {files[0]}")
    for k, v in summary(p).items():
        print(f"  {k:20s} {v:>5,}")
    if p["quality"]:
        print("읽지 못한 칸(처음 10건):")
        for q in p["quality"][:10]:
            print(f"  {q['sheet']}!{q['cell']:5s} {(q['raw'] or '')[:30]!r} — {q['reason']}")
    if "--apply" not in argv:
        print("\nDB는 바꾸지 않았습니다. 넣으려면 --apply 를 붙이세요(기존 Task 기준·실적을 지우고 다시 채움).")
        return 0

    from ..db import DB_KIND, Base, SessionLocal, engine, ensure_columns

    if DB_KIND != "postgres" and "--allow-sqlite" not in argv:
        print("Postgres에 연결하지 못했습니다(.env 확인). 로컬 SQLite에 넣으려면 --allow-sqlite")
        return 1
    print(f"\n대상 DB: {DB_KIND} {engine.url.render_as_string(hide_password=True)}")
    Base.metadata.create_all(engine)
    ensure_columns(engine)
    with SessionLocal() as db:
        counts = load(db, p)
    for k, v in counts.items():
        print(f"  {k:26s} {v:>5,}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
