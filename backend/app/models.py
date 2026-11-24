from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Task(Base):
    """Task 기준 데이터(템플릿). 화면에서 고치지 않고 CSV 가져오기로만 바꾼다."""
    __tablename__ = "npd_tasks"
    no: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    phase: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    basis: Mapped[str] = mapped_column(String(10), default="완료")
    predecessors: Mapped[str | None] = mapped_column(String(200), nullable=True)  # "3,4"
    buffer_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    dept: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 담당부서(역산 계산기)
    fixed_end: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 고정 완료 D-영업일(밀리면 즉시 빨강)
    # 입력 원천: 엑셀 | 앱 | 디자인 시트 | 없음. 엑셀·앱이 아닌 Task는 입력이 들어오기 전까지 신호등 판정에서 뺀다.
    # 빈 값(NULL) = 지정 안 함 → 예전처럼 모두 판정(변환기를 쓰기 전 데이터)
    input_source: Mapped[str | None] = mapped_column(String(20), nullable=True)


class TaskCombo(Base):
    """Task × 유형|프로세스(8조합)별 착수 역산일·소요일. 소요 0 = 그 조합에서 생략. 채우기: app.tools.import_npd"""
    __tablename__ = "npd_task_combo"
    task_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    type_process: Mapped[str] = mapped_column(String(40), primary_key=True)  # "NEW|표준"
    start_offset: Mapped[int] = mapped_column(Integer)
    duration: Mapped[int] = mapped_column(Integer)


class Holiday(Base):
    __tablename__ = "npd_holidays"
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20), default="공휴일")  # 공휴일 | 공동연차
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Product(Base):
    __tablename__ = "npd_products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)  # 「제품A」처럼 바꿔 쓴 이름
    launch_date: Mapped[date] = mapped_column(Date)
    product_type: Mapped[str] = mapped_column(String(20), default="NEW")
    process: Mapped[str] = mapped_column(String(20), default="표준")
    # 아래는 NPD 엑셀에서 가져온 제품만 값이 있다(app.tools.import_npd)
    source_sheet: Mapped[str | None] = mapped_column(String(50), nullable=True)
    excel_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cat: Mapped[str | None] = mapped_column(String(50), nullable=True)
    maker: Mapped[str | None] = mapped_column(String(50), nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)  # 비고·이슈(⚠ 문구 = 결정 안건 후보)


class Actual(Base):
    __tablename__ = "npd_actuals"
    __table_args__ = (UniqueConstraint("product_id", "task_no"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("npd_products.id", ondelete="CASCADE"))
    task_no: Mapped[int] = mapped_column(ForeignKey("npd_tasks.no"))
    actual_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    state: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 완료 | 예정변경 | 해당없음 (빈칸 = 화면 입력)
    change_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # 변경 예정일
    estimated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # True = 완료일을 계획일로 추정(●)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)


class DataQuality(Base):
    """엑셀에서 해석하지 못한 칸 목록(시트·칸·원문·사유). 가져올 때마다 새로 채운다."""
    __tablename__ = "npd_data_quality"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sheet: Mapped[str] = mapped_column(String(50))
    cell: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "N8"
    product: Mapped[str | None] = mapped_column(String(100), nullable=True)
    step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Setting(Base):
    __tablename__ = "npd_settings"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
