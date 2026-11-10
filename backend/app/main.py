from __future__ import annotations

import csv
import io
import os
from contextlib import asynccontextmanager
from datetime import date

from fastapi import APIRouter, Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import actions, auth, clone, notify
from .db import DB_KIND, Base, engine, get_db, SessionLocal
from .engine.absorb import absorb
from .engine.backcalc import TaskDef, schedule
from .engine.calendar import BusinessCalendar, HolidayNotRegistered
from .engine.concurrent import overlaps
from .engine.status import judge
from .models import Actual, Holiday, Product, Setting, Task
from .seed import parse_task_rows, seed

Base.metadata.create_all(engine)
with SessionLocal() as _s:
    seed(_s)



@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop = notify.start_scheduler(check_alerts)  # Slack 지연 알림 주기 점검
    yield
    if stop:
        stop.set()


app = FastAPI(title="NPD 일정·이력 관리 API", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(actions.router)
app.include_router(clone.router)
# 아래 api 라우터의 경로는 모두 로그인(Bearer 토큰)이 필요하다. /api/health 만 예외.
api = APIRouter(dependencies=[Depends(auth.current_user)])


# ---------- helpers ----------
def calendar_from_db(db: Session) -> BusinessCalendar:
    return BusinessCalendar([h.date for h in db.scalars(select(Holiday))])


def taskdefs_from_db(db: Session) -> list[TaskDef]:
    out = []
    for t in db.scalars(select(Task).order_by(Task.no)):
        preds = [int(x) for x in (t.predecessors or "").replace(" ", "").split(",") if x]
        out.append(TaskDef(t.no, t.name, t.start_offset, t.duration, t.basis, t.phase, preds,
                           t.buffer_days, t.note))
    return out


def setting_int(db: Session, key: str) -> int:
    s = db.get(Setting, key)
    if s is None:
        raise HTTPException(500, f"설정 {key} 없음")
    return int(s.value)


def get_product(db: Session, pid: int) -> Product:
    p = db.get(Product, pid)
    if p is None:
        raise HTTPException(404, "제품 없음")
    return p


def scheduled(db: Session, p: Product):
    try:
        return schedule(p.launch_date, taskdefs_from_db(db), calendar_from_db(db))
    except HolidayNotRegistered as e:
        raise HTTPException(422, f"C-05: {e}") from e


def schedule_rows(db: Session, p: Product, as_of: date) -> list[dict]:
    """예정 일정 + 실적 + 신호등 판정"""
    cal = calendar_from_db(db)
    threshold = setting_int(db, "yellow_threshold")
    actuals = {a.task_no: a.actual_end for a in db.scalars(select(Actual).where(Actual.product_id == p.id))}
    rows = []
    for t in scheduled(db, p):
        d = t.to_dict()
        a = actuals.get(t.no)
        d["actual_end"] = a.isoformat() if a else None
        d |= judge(t.end, a, as_of, threshold, cal)
        rows.append(d)
    return rows


def check_alerts(as_of: date) -> dict:
    """모든 제품의 빨강 Task를 점검해 새로 생긴 것만 Slack으로 보낸다."""
    out = {}
    with SessionLocal() as db:
        for p in db.scalars(select(Product).order_by(Product.id)):
            try:
                out[p.name] = notify.notify_red(db, p, schedule_rows(db, p, as_of))
            except HTTPException as e:  # C-05 등: 일정 계산 불가 제품은 건너뜀
                out[p.name] = f"건너뜀: {e.detail}"
    return out


# ---------- schemas ----------
class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    launch_date: date
    product_type: str = "NEW"
    process: str = "표준"


class ActualIn(BaseModel):
    actual_end: date | None


class SettingIn(BaseModel):
    value: str


class AbsorbIn(BaseModel):
    task_no: int
    delay_days: int = Field(ge=0)


# ---------- routes ----------
@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    tasks = list(db.scalars(select(Task)))
    return {"status": "ok", "db": DB_KIND, "tasks": len(tasks),
            "tasks_needing_check": sum(1 for t in tasks if t.start_offset is None or t.duration is None)}


@api.get("/api/tasks")
def list_tasks(db: Session = Depends(get_db)):
    cols = ["no", "name", "phase", "start_offset", "duration", "basis", "predecessors", "buffer_days", "note"]
    return [{c: getattr(t, c) for c in cols} for t in db.scalars(select(Task).order_by(Task.no))]


@api.post("/api/tasks/import")
async def import_tasks(file: UploadFile, db: Session = Depends(get_db)):
    """엑셀에서 옮긴 Task 기준 데이터 CSV로 전체를 바꾼다(열: no,name,phase,start_offset,duration,basis,predecessors,buffer_days,note)."""
    raw = (await file.read()).decode("utf-8-sig")
    try:
        rows = parse_task_rows(list(csv.DictReader(io.StringIO(raw))))
    except (KeyError, ValueError) as e:
        raise HTTPException(400, f"CSV 형식 오류: {e}") from e
    db.execute(delete(Actual))
    db.execute(delete(Task))
    db.add_all(rows)
    db.commit()
    return {"imported": len(rows)}


@api.get("/api/holidays")
def list_holidays(db: Session = Depends(get_db)):
    return [{"date": h.date.isoformat(), "name": h.name, "kind": h.kind, "note": h.note}
            for h in db.scalars(select(Holiday).order_by(Holiday.date))]


@api.get("/api/settings")
def list_settings(db: Session = Depends(get_db)):
    return {s.key: {"value": s.value, "note": s.note} for s in db.scalars(select(Setting))}


@api.put("/api/settings/{key}")
def put_setting(key: str, body: SettingIn, db: Session = Depends(get_db)):
    s = db.get(Setting, key)
    if s is None:
        raise HTTPException(404, "설정 없음")
    try:
        int(body.value)
    except ValueError as e:
        raise HTTPException(400, "정수만 입력") from e
    s.value = body.value
    db.commit()
    return {"key": key, "value": s.value}


@api.get("/api/products")
def list_products(db: Session = Depends(get_db)):
    return [{"id": p.id, "name": p.name, "launch_date": p.launch_date.isoformat(),
             "product_type": p.product_type, "process": p.process}
            for p in db.scalars(select(Product).order_by(Product.id))]


@api.post("/api/products", status_code=201)
def create_product(body: ProductIn, db: Session = Depends(get_db)):
    cal = calendar_from_db(db)
    tasks = taskdefs_from_db(db)
    try:  # C-05: 미등록 연도면 생성 막음
        schedule(body.launch_date, tasks, cal)
    except HolidayNotRegistered as e:
        raise HTTPException(422, f"C-05: 프로젝트를 만들 수 없습니다. {e}") from e
    if db.scalar(select(Product).where(Product.name == body.name)):
        raise HTTPException(409, "같은 이름의 제품이 있습니다")
    p = Product(**body.model_dump())
    db.add(p)
    db.commit()
    return {"id": p.id}


@api.delete("/api/products/{pid}")
def delete_product(pid: int, db: Session = Depends(get_db)):
    p = get_product(db, pid)
    db.execute(delete(Actual).where(Actual.product_id == pid))
    db.delete(p)
    db.commit()
    return {"deleted": pid}


@api.get("/api/products/{pid}/schedule")
def product_schedule(pid: int, as_of: date | None = None, db: Session = Depends(get_db)):
    p = get_product(db, pid)
    as_of = as_of or date.today()
    threshold = setting_int(db, "yellow_threshold")
    rows = schedule_rows(db, p, as_of)
    if as_of == date.today():  # 가정 기준일(과거·미래)로 볼 때는 알림 보내지 않음
        notify.notify_red(db, p, rows)
    return {"product": {"id": p.id, "name": p.name, "launch_date": p.launch_date.isoformat(),
                        "product_type": p.product_type, "process": p.process},
            "as_of": as_of.isoformat(), "threshold": threshold, "tasks": rows,
            "red_count": sum(1 for r in rows if r["signal"] == "빨강")}


@api.put("/api/products/{pid}/actuals/{task_no}")
def put_actual(pid: int, task_no: int, body: ActualIn, db: Session = Depends(get_db)):
    get_product(db, pid)
    if db.get(Task, task_no) is None:
        raise HTTPException(404, "Task 없음")
    a = db.scalar(select(Actual).where(Actual.product_id == pid, Actual.task_no == task_no))
    if a is None:
        a = Actual(product_id=pid, task_no=task_no)
        db.add(a)
    a.actual_end = body.actual_end
    db.commit()
    notify.notify_red(db, get_product(db, pid), schedule_rows(db, get_product(db, pid), date.today()))
    return {"product_id": pid, "task_no": task_no,
            "actual_end": body.actual_end.isoformat() if body.actual_end else None}


@api.get("/api/concurrent")
def concurrent(ids: str, db: Session = Depends(get_db)):
    pids = [int(x) for x in ids.split(",") if x.strip()]
    if len(pids) < 2:
        raise HTTPException(400, "제품을 2개 이상 고르세요")
    data = []
    for pid in pids:
        p = get_product(db, pid)
        data.append((p.name, scheduled(db, p)))
    return overlaps(data)


@api.post("/api/products/{pid}/absorb")
def absorb_delay(pid: int, body: AbsorbIn, db: Session = Depends(get_db)):
    p = get_product(db, pid)
    try:
        result = absorb(scheduled(db, p), body.task_no, body.delay_days,
                        setting_int(db, "absorb_limit_task"), p.launch_date, calendar_from_db(db))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    notify.notify_absorb(db, p, result)
    return result


@api.get("/api/alerts/slack")
def slack_status():
    return notify.status()


@api.post("/api/alerts/slack/test")
def slack_test(user: auth.User = Depends(auth.current_user)):
    try:
        notify.post(f":white_check_mark: NPD 일정 관리 지연 알림 연결 시험 ({user.name})")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e)) from e
    return {"sent": True}


@api.post("/api/alerts/check")
def alerts_check():
    """지금 바로 모든 제품의 빨강 Task를 점검(새로 생긴 것만 Slack으로)."""
    if not notify.configured():
        raise HTTPException(400, "Slack 설정 없음: backend/.env에 SLACK_WEBHOOK_URL 또는 SLACK_BOT_TOKEN을 넣으세요")
    return {"queued": check_alerts(date.today())}


app.include_router(api)
