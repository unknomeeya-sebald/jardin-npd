"""일정관리 화면(data/clone/npd_schedule.html)에 내장된 데이터를 DB npd_sched_* 테이블에 넣는다.

    python -m app.tools.import_schedule                 # .env 의 Postgres(Supabase)에 넣음
    python -m app.tools.import_schedule --allow-sqlite  # Postgres 연결이 안 돼도 로컬 SQLite에 넣음

- 넣는 것: 화면 내장 JSON(data: Task·순서도·설정), 순서도 원문(mer), 판 정보(npd-rel),
  제품정보(npd-prodinfo), 정본 엑셀(npd-canon, base64 xlsx)의 NEW·표기수정·역산 계산기·기준일정 시트
- npd_sched_* 테이블만 비우고 다시 채운다(여러 번 실행해도 결과 같음). 기존 npd_tasks·npd_products 등은 건드리지 않는다.
"""
from __future__ import annotations

import base64
import io
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..sched_models import (SchedFlowEdge, SchedFlowNode, SchedMeta, SchedProduct, SchedProductStep,
                            SchedSheet, SchedStdDays, SchedTask)

HTML = Path(__file__).resolve().parents[2] / "data" / "clone" / "npd_schedule.html"
SOURCE_URL = "https://jardin-npd.pages.dev/nb"


# ---------- 읽기 ----------
def _block(html: str, id_: str) -> str:
    m = re.search(r'<script id="%s"[^>]*>(.*?)</script>' % re.escape(id_), html, re.S)
    if m is None:
        raise ValueError(f"화면 파일에 {id_} 블록이 없습니다")
    return m.group(1).strip()


def _txt(v) -> str | None:
    """칸 값 → 글. 날짜는 YYYY-MM-DD, 빈칸은 None"""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None


def _date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def _head(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _json_cell(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _sheet_rows(ws) -> list[list]:
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    while rows and not any(v not in (None, "") for v in rows[-1]):
        rows.pop()
    out = []
    for r in rows:
        while r and r[-1] in (None, ""):
            r.pop()
        out.append([_json_cell(v) for v in r])
    return out


def _header_row(rows: list[tuple], key: str) -> int:
    for i, r in enumerate(rows):
        if any(_head(v) == key for v in r):
            return i
    raise ValueError(f"머리글 「{key}」 행을 찾지 못했습니다")


def _products(rows: list[tuple], sheet: str) -> list[dict]:
    """NEW: 제품 행 + 바로 아래 「진행사항」 행 / 표기수정: 제품 행만"""
    h = _header_row(rows, "품목")
    head = {(_head(v)): j for j, v in enumerate(rows[h]) if _head(v)}
    depts = rows[h - 1] if h > 0 else ()
    g = lambda r, k: r[head[k]] if k in head and head[k] < len(r) else None  # noqa: E731
    note_col = next((j for k, j in head.items() if k.startswith("비고")), None)
    launch_key = "출시예상일" if "출시예상일" in head else "적용예상일"
    first_step = head["구분"] + 1 if "구분" in head else head[launch_key] + 1
    last_step = (note_col if note_col is not None else max(head.values()) + 1)
    step_cols = [j for j in range(first_step, last_step) if _head(rows[h][j])]

    out, i = [], h + 1
    while i < len(rows):
        r = rows[i]
        name = _txt(g(r, "품목"))
        kind = _txt(g(r, "구분"))
        if not name or kind == "진행사항":
            i += 1
            continue
        status = None
        if i + 1 < len(rows) and _txt(g(rows[i + 1], "구분")) == "진행사항":
            status = rows[i + 1]
        steps = []
        for j in step_cols:
            pv = r[j] if j < len(r) else None
            sv = status[j] if status is not None and j < len(status) else None
            steps.append(dict(col=j, step=_head(rows[h][j]), dept=_txt(depts[j]) if j < len(depts) else None,
                              plan_text=_txt(pv), plan_date=_date(pv), status_text=_txt(sv), status_date=_date(sv)))
        lv = g(r, launch_key)
        out.append(dict(
            sheet=sheet, seq=len(out) + 1, researcher=_txt(g(r, "연구원")), marketer=_txt(g(r, "마케팅")),
            cat=_txt(g(r, "CAT")), name=name, shelf_life=_txt(g(r, "소비기한")), maker=_txt(g(r, "제조사")),
            product_type=_txt(g(r, "유형")), process=_txt(g(r, "프로세스")), launch_text=_txt(lv),
            launch_date=_date(lv), division=kind,
            note=_txt(r[note_col]) if note_col is not None and note_col < len(r) else None, steps=steps,
        ))
        i += 2 if status is not None else 1
    return out


def _std_days(rows: list[tuple]) -> list[dict]:
    h = _header_row(rows, "유형|프로세스")
    c0 = next(j for j, v in enumerate(rows[h]) if _head(v) == "유형|프로세스")
    steps = [(j, _head(v)) for j, v in enumerate(rows[h]) if j > c0 and _head(v)]
    out = []
    for r in rows[h + 1:]:
        tp = _txt(r[c0]) if c0 < len(r) else None
        if not tp:
            continue
        for j, s in steps:
            v = r[j] if j < len(r) else None
            out.append(dict(type_process=tp, step=s, days=int(v) if isinstance(v, (int, float)) else None))
    return out


def parse(path: Path = HTML) -> dict:
    import openpyxl

    html = path.read_text(encoding="utf-8")
    data = json.loads(_block(html, "data"))
    canon_b64 = _block(html, "npd-canon")
    wb = openpyxl.load_workbook(io.BytesIO(base64.b64decode(canon_b64)), data_only=True)
    raw = {ws.title: [tuple(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}

    crit = {int(k): v for k, v in data.get("crit", {}).items()}
    tasks = [dict(no=t["no"], stage=t["stage"], name=t["name"], owner=t.get("owner"), path=t.get("path"),
                  days=t.get("days"), start_d=t.get("start"), end_d=t.get("end"),
                  orgs=",".join(t.get("orgs") or []) or None, done_criterion=crit.get(t["no"]))
             for t in data["tasks"]]
    node_tasks, side = data.get("nodeTasks", {}), data.get("side", {})
    nodes = [dict(id=n["id"], seq=i + 1, label=n["label"], shape=n.get("shape"),
                  task_nos=",".join(str(x) for x in node_tasks.get(n["id"], [])) or None,
                  side_note=side.get(n["id"]) or None)
             for i, n in enumerate(data["nodes"])]
    edges = [dict(seq=i + 1, src=e["src"], dst=e["dst"], label=e.get("label") or None, kind=e.get("kind"))
             for i, e in enumerate(data["edges"])]

    products = []
    for sheet in ("NEW", "표기수정"):
        if sheet in raw:
            products += _products(raw[sheet], sheet)
    std = _std_days(raw["기준일정"]) if "기준일정" in raw else []
    sheets = [dict(name=ws.title, seq=i + 1, rows=_sheet_rows(ws)) for i, ws in enumerate(wb.worksheets)]

    J = lambda v: json.dumps(v, ensure_ascii=False)  # noqa: E731
    meta = {
        "source": (J({"url": SOURCE_URL, "file": "data/clone/npd_schedule.html",
                      "imported_at": datetime.now().isoformat(timespec="seconds")}), "가져온 곳·시각"),
        "ver": (J(data.get("ver")), "화면 판(npd-ver)"),
        "bounds": (J(data.get("bounds")), "단계 경계 D-값"),
        "dept_order": (J(data.get("order")), "줄이는 순서 — 부서 중요도(위부터 먼저 줄임)"),
        "dept_protect": (J(data.get("protect")), "줄이지 않는 부서"),
        "cols": (J(data.get("cols")), "표 칸 이름"),
        "crit": (J(data.get("crit")), "Task별 완료 기준(npd_sched_tasks.done_criterion 과 같음)"),
        "side": (J(side), "순서도 노드 옆 설명(npd_sched_flow_nodes.side_note 와 같음)"),
        "node_tasks": (J(node_tasks), "순서도 노드 ↔ Task 번호"),
        "nbmap": (J(data.get("nbmap")), "NEW 시트 단계 칸 ↔ Task 번호 대응"),
        "holidays_text": (data.get("holi") or "", "공휴일 목록 원문(화면 「공휴일 목록」). npd_holidays 와 별개"),
        "canon_path": (J(data.get("canon")), "정본 폴더 경로"),
        "release": (J(json.loads(_block(html, "npd-rel"))), "정본 판 정보(npd-rel)"),
        "prodinfo": (J(json.loads(_block(html, "npd-prodinfo"))), "물류팀 제품정보 기준(npd-prodinfo)"),
        "mermaid": (_block(html, "mer"), "순서도 Mermaid 원문"),
        "canon_xlsx_b64": (canon_b64, "정본 엑셀 원본(base64 xlsx) — 시트는 npd_sched_sheets 에 풀어 둠"),
    }
    return dict(tasks=tasks, nodes=nodes, edges=edges, products=products, std=std, sheets=sheets, meta=meta)


# ---------- 쓰기 ----------
def load(db: Session, p: dict) -> dict[str, int]:
    for M in (SchedProductStep, SchedProduct, SchedFlowEdge, SchedFlowNode, SchedTask, SchedStdDays,
              SchedSheet, SchedMeta):
        db.execute(delete(M))
    db.add_all(SchedTask(**t) for t in p["tasks"])
    db.add_all(SchedFlowNode(**n) for n in p["nodes"])
    db.add_all(SchedFlowEdge(**e) for e in p["edges"])
    n_steps = 0
    for pr in p["products"]:
        pr = dict(pr)
        steps = pr.pop("steps")
        row = SchedProduct(**pr)
        db.add(row)
        db.flush()
        db.add_all(SchedProductStep(product_id=row.id, **s) for s in steps)
        n_steps += len(steps)
    db.add_all(SchedStdDays(**s) for s in p["std"])
    db.add_all(SchedSheet(name=s["name"], seq=s["seq"], n_rows=len(s["rows"]),
                          n_cols=max((len(r) for r in s["rows"]), default=0),
                          rows_json=json.dumps(s["rows"], ensure_ascii=False)) for s in p["sheets"])
    db.add_all(SchedMeta(key=k, value=v, note=n) for k, (v, n) in p["meta"].items())
    db.commit()
    return {"npd_sched_tasks": len(p["tasks"]), "npd_sched_flow_nodes": len(p["nodes"]),
            "npd_sched_flow_edges": len(p["edges"]), "npd_sched_products": len(p["products"]),
            "npd_sched_product_steps": n_steps, "npd_sched_std_days": len(p["std"]),
            "npd_sched_sheets": len(p["sheets"]), "npd_sched_meta": len(p["meta"])}


def main() -> int:
    from ..db import DB_KIND, Base, SessionLocal, engine

    if DB_KIND != "postgres" and "--allow-sqlite" not in sys.argv:
        print("Postgres에 연결하지 못했습니다(.env 확인). 로컬 SQLite에 넣으려면 --allow-sqlite")
        return 1
    print(f"대상 DB: {DB_KIND} {engine.url.render_as_string(hide_password=True)}")
    p = parse()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        counts = load(db, p)
    for k, v in counts.items():
        print(f"  {k:26s} {v:>5,}건")
    by_sheet: dict[str, int] = {}
    for pr in p["products"]:
        by_sheet[pr["sheet"]] = by_sheet.get(pr["sheet"], 0) + 1
    print("  제품(시트별):", ", ".join(f"{k} {v}" for k, v in by_sheet.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
