"""연동 예상일정과 신호등 판정(재설계서 「연동 계산 규칙」·「신호등 기준」).

예상일정
- 기준일정(출시일 역산)은 그대로 두고, 선행 Task가 기준보다 늦어진 만큼만 후행을 민다.
  밀리는 영업일 = MAX(선행의 지연 − 선행 기준 종료와 내 기준 착수 사이 여유), 0 미만은 0.
  기준일정이 선후관계와 딱 맞으면 「예상 착수 = MAX(기준 착수, 선행 예상 종료)」와 같은 값이다.
- 실적 완료일이 있으면 그 날, 없고 변경 예정일이 있으면 그 날이 예상 종료다.
- 해당 없음·그 유형에서 생략·값 없는 Task는 계산에서 빼고, 선행의 지연만 후행으로 넘긴다.
- 변경 예정일이 기준일보다 앞서면(지난 날짜) 그 날 완료한 것으로 본다(past_as_done).
- 입력이 없는 Task라도 그 뒤(후행, 건너서도) Task가 완료됐으면 완료로 추정한다(infer_done).
  엑셀에는 39 Task 중 17단계만 칸이 있어, 이 추정이 없으면 칸 없는 Task가 계속 「지남·미완료」로 남는다.
- 예상 출시일 = MAX(출시일, 모든 Task의 예상 종료). 출시 영향 = 출시일 → 예상 출시일 영업일.

Task 신호등
- 회색: 완료 또는 해당 없음(생략)
- 빨강: 예상 종료일이 지났는데 미완료 / 고정일 Task가 기준보다 늦음 / 예상 종료가 출시일을 넘김
- 노랑: 기준보다 늦지만 출시일 안 / 남은 여유(기준일 → 예상 종료 영업일) ≤ 기준값
- 초록: 그 외
- 판정 제외(확인 필요): 입력 원천이 엑셀·앱이 아닌 Task(디자인 시트 미연동, 입력처 없음)에 입력이 하나도 없을 때.
  예상일은 계산해 후행으로 넘기지만 기한 지남·늦음으로 빨강·노랑을 켜지 않는다. 완료 추정은 그대로 회색.
제품 신호등: 출시 영향 > 0 빨강 / 출시 영향 0인데 빨강 Task 있음 노랑 / 그 외 초록
"""
from __future__ import annotations

from datetime import date

from .backcalc import ScheduledTask
from .calendar import BusinessCalendar
from .status import GREEN, NONE, RED, YELLOW

GRAY = "회색"
JUDGED_SOURCES = (None, "엑셀", "앱")  # None = 지정 안 함(예전 데이터) → 판정


def excluded_reason(source: str | None) -> str | None:
    """판정에서 빼는 Task면 그 사유, 아니면 None"""
    if source in JUDGED_SOURCES:
        return None
    if source == "디자인 시트":
        return "입력 원천 디자인 시트(아직 연동 안 함) — 판정 제외"
    return "입력처 없음 — 판정 제외"
DONE, CHANGED, NA = "완료", "예정변경", "해당없음"


def _order(tasks: list[ScheduledTask]) -> list[ScheduledTask]:
    """선행이 먼저 오게 줄 세운다. 선후관계가 돌면 ValueError."""
    by_no = {t.no: t for t in tasks}
    left = {t.no: {p for p in t.predecessors if p in by_no and p != t.no} for t in tasks}
    out = []
    while left:
        ready = sorted(no for no, ps in left.items() if not ps)
        if not ready:
            raise ValueError(f"Task 선후관계가 돌고 있습니다: {sorted(left)}")
        for no in ready:
            out.append(by_no[no])
            del left[no]
        for ps in left.values():
            ps.difference_update(ready)
    return out


def past_as_done(inputs: dict[int, dict], as_of: date) -> dict[int, dict]:
    """변경 예정일이 기준일보다 앞선(지난) Task는 그 날 완료한 것으로 본 새 inputs.

    엑셀 「진행사항」 칸의 날짜는 처음엔 예정일이지만, 그 날이 지나도 담당자가 ●로 바꾸지 않는 경우가 많다.
    기준일 당일·이후 날짜는 그대로 예정일이다. 실적 완료일·완료·해당 없음이 있는 Task는 건드리지 않는다.
    """
    out = dict(inputs)
    for no, i in inputs.items():
        d = i.get("change_date")
        if d and d < as_of and not i.get("actual_end") and i.get("state") not in (DONE, NA):
            out[no] = i | {"state": DONE, "actual_end": d, "estimated": False, "from_past": True}
    return out


def infer_done(tasks: list[ScheduledTask], inputs: dict[int, dict]) -> dict[int, dict]:
    """입력이 없는 Task 가운데 후행(건너서도) Task가 완료된 것을 완료 추정으로 채운 새 inputs."""
    by_no = {t.no: t for t in tasks}

    def is_done(no: int) -> bool:
        i = inputs.get(no) or {}
        return bool(i.get("actual_end")) or i.get("state") == DONE

    out, seen = dict(inputs), set()
    stack = [p for t in tasks if is_done(t.no) for p in t.predecessors]
    while stack:
        no = stack.pop()
        if no in seen or no not in by_no:
            continue
        seen.add(no)
        i = inputs.get(no) or {}
        if not (i.get("state") or i.get("actual_end") or i.get("change_date")):
            out[no] = {"state": DONE, "estimated": True, "inferred": True}
        stack.extend(by_no[no].predecessors)
    return out


def expect(tasks: list[ScheduledTask], inputs: dict[int, dict], cal: BusinessCalendar) -> dict[int, dict]:
    """Task 번호 → {active, expected_start, expected_end, delay, push}.

    inputs[no] = {"state": 완료|예정변경|해당없음|None, "actual_end": date|None, "change_date": date|None}
    delay = 기준 종료 → 예상 종료 영업일(늦으면 +), push = 선행 때문에 밀린 영업일.
    """
    out: dict[int, dict] = {}
    carry: dict[int, list[tuple[date, date]]] = {}  # 후행에 넘기는 (기준 종료, 예상 종료)들
    for t in _order(tasks):
        i = inputs.get(t.no) or {}
        pairs = [x for p in t.predecessors for x in carry.get(p, [])]
        if t.start is None or t.end is None or i.get("state") == NA:
            carry[t.no] = pairs  # 계산에서 빠지는 Task: 선행의 지연만 그대로 넘김
            out[t.no] = dict(active=False, expected_start=None, expected_end=None, delay=None, push=0)
            continue
        push = 0
        for b, e in pairs:
            if e > b:
                push = max(push, cal.between(b, e) - max(0, cal.between(b, t.start)))
        start, end = (cal.add(t.start, push), cal.add(t.end, push)) if push else (t.start, t.end)
        if i.get("actual_end"):
            end = i["actual_end"]
        elif i.get("state") == DONE:
            end = t.end  # 완료인데 완료일을 모름: 기준대로 끝난 것으로 봄
        elif i.get("change_date"):
            end = i["change_date"]
        carry[t.no] = [(t.end, end)]
        out[t.no] = dict(active=True, expected_start=start, expected_end=end,
                         delay=cal.between(t.end, end), push=push)
    return out


def judge(x: dict, i: dict, as_of: date, threshold: int, launch: date, fixed: bool,
          cal: BusinessCalendar, excluded: str | None = None) -> dict:
    """Task 하나의 신호등. x = expect() 결과 한 건, i = 입력(state·actual_end·estimated·skip_reason)."""
    if i.get("state") == NA:
        return {"signal": GRAY, "slack": None, "reason": i.get("skip_reason") or "해당 없음"}
    if not x["active"]:
        return {"signal": NONE, "slack": None, "reason": "예정 종료일 없음"}
    end, late = x["expected_end"], x["delay"]
    if i.get("actual_end") or i.get("state") == DONE:
        guessed = bool(i.get("estimated")) or not i.get("actual_end")
        why = f"완료 (지난 예정일 {end.month}/{end.day}을 완료일로 봄)" if i.get("from_past") else \
            "완료 (후행 Task 완료로 추정)" if i.get("inferred") else "완료 (완료일 추정)" if guessed else "완료"
        if late > 0 and not guessed:
            why += f" · 기준보다 {late}영업일 늦음"
        return {"signal": GRAY, "slack": None, "reason": why}
    if excluded and not i.get("change_date"):  # 입력이 들어오면 그때부터 판정
        return {"signal": NONE, "slack": None, "reason": excluded}
    slack = cal.between(as_of, end)
    if as_of > end:
        return {"signal": RED, "slack": slack, "reason": "예상 종료일 지남, 미완료"}
    if fixed and late > 0:
        return {"signal": RED, "slack": slack, "reason": f"고정일 Task가 기준보다 {late}영업일 늦음"}
    if end > launch:
        return {"signal": RED, "slack": slack,
                "reason": f"예상 종료가 출시일보다 {cal.between(launch, end)}영업일 늦음"}
    if late > 0:
        return {"signal": YELLOW, "slack": slack, "reason": f"기준보다 {late}영업일 늦음(출시일 안)"}
    if slack <= threshold:
        return {"signal": YELLOW, "slack": slack, "reason": f"남은 여유 {slack} ≤ 기준값 {threshold}"}
    return {"signal": GREEN, "slack": slack, "reason": f"남은 여유 {slack} > 기준값 {threshold}"}


def product_signal(rows: list[dict], launch: date, cal: BusinessCalendar) -> dict:
    """rows = Task별 {"signal", "expected_end": date|None}. 예상 출시일·출시 영향·제품 신호등."""
    ends = [r["expected_end"] for r in rows if r.get("expected_end")]
    expected = max([launch, *ends])
    impact = cal.between(launch, expected)
    reds = sum(r["signal"] == RED for r in rows)
    signal = RED if impact > 0 else YELLOW if reds else GREEN
    return {"expected_launch": expected, "launch_impact_days": impact, "signal": signal}
