"""일정관리(복제 화면 jardin-npd.pages.dev/nb) 데이터를 담는 테이블.

기존 npd_tasks·npd_products 등(간트·신호등 화면용)과 섞지 않으려고 npd_sched_* 로 따로 둔다.
채우기: python -m app.tools.import_schedule
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class SchedTask(Base):
    """Task 39개 — 화면 내장 data.tasks (+ data.crit 완료 기준)"""
    __tablename__ = "npd_sched_tasks"
    no: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    path: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 임계 | 병행 …
    days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_d: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 출시 D-값(영업일)
    end_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    orgs: Mapped[str | None] = mapped_column(String(200), nullable=True)  # "마케팅,연구"
    done_criterion: Mapped[str | None] = mapped_column(String(100), nullable=True)


class SchedFlowNode(Base):
    """순서도 노드 — data.nodes (+ nodeTasks·side)"""
    __tablename__ = "npd_sched_flow_nodes"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(Text)
    shape: Mapped[str | None] = mapped_column(String(20), nullable=True)
    task_nos: Mapped[str | None] = mapped_column(String(100), nullable=True)  # "8,9"
    side_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class SchedFlowEdge(Base):
    """순서도 연결선 — data.edges"""
    __tablename__ = "npd_sched_flow_edges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seq: Mapped[int] = mapped_column(Integer)
    src: Mapped[str] = mapped_column(String(20))
    dst: Mapped[str] = mapped_column(String(20))
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)


class SchedProduct(Base):
    """정본 엑셀의 제품 — NEW 시트(신제품·리뉴얼) · 표기수정 시트"""
    __tablename__ = "npd_sched_products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sheet: Mapped[str] = mapped_column(String(20))  # NEW | 표기수정
    seq: Mapped[int] = mapped_column(Integer)  # 시트 안 순서(1부터)
    researcher: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 연구원
    marketer: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 마케팅
    cat: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name: Mapped[str] = mapped_column(Text)  # 품목
    shelf_life: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 소비기한(NEW만)
    maker: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 유형
    process: Mapped[str | None] = mapped_column(String(20), nullable=True)
    launch_text: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 출시예상일·적용예상일 원문
    launch_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # 날짜로 적힌 경우만
    division: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 구분(NEW: 표준)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 비고 · 이슈


class SchedProductStep(Base):
    """제품 × 단계 칸 — 계획(날짜 또는 글) · 진행사항(●, 메모)"""
    __tablename__ = "npd_sched_product_steps"
    __table_args__ = (UniqueConstraint("product_id", "col"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("npd_sched_products.id", ondelete="CASCADE"))
    col: Mapped[int] = mapped_column(Integer)  # 엑셀 열 번호(0부터, 순서 유지용)
    step: Mapped[str] = mapped_column(String(100))  # 단계 이름(줄바꿈은 공백으로)
    dept: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 담당 부서(NEW 머리 위 칸)
    plan_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class SchedStdDays(Base):
    """기준일정 시트 — 유형|프로세스별 단계 역산 영업일"""
    __tablename__ = "npd_sched_std_days"
    __table_args__ = (UniqueConstraint("type_process", "step"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type_process: Mapped[str] = mapped_column(String(50))  # "NEW|표준"
    step: Mapped[str] = mapped_column(String(100))
    days: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SchedSheet(Base):
    """정본 엑셀 시트 원본 행(JSON) — 구조화하지 않은 칸(역산 계산기 등)까지 빠짐없이 보관"""
    __tablename__ = "npd_sched_sheets"
    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer)
    n_rows: Mapped[int] = mapped_column(Integer)
    n_cols: Mapped[int] = mapped_column(Integer)
    rows_json: Mapped[str] = mapped_column(Text)


class SchedMeta(Base):
    """화면 설정·판 정보 등 (값은 JSON 또는 글)"""
    __tablename__ = "npd_sched_meta"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
