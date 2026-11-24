"""연동 예상일정·신호등(app.engine.linked)"""
from datetime import date

import pytest

from app.engine.backcalc import TaskDef, schedule
from app.engine.calendar import BusinessCalendar
from app.engine.linked import expect, infer_done, judge, product_signal

CAL = BusinessCalendar([date(2027, 1, 1)], registered_years={2026, 2027})
LAUNCH = date(2027, 3, 26)  # 금
# 1 → 2 → 4(출시) 는 여유 없이 이어지고, 3 → 4 는 여유 5영업일. 5는 값 없는 Task
DEFS = [
    TaskDef(1, "가", 20, 5),
    TaskDef(2, "나", 15, 10, predecessors=[1]),
    TaskDef(3, "다", 15, 5, predecessors=[1]),
    TaskDef(4, "출시", 5, 5, predecessors=[2, 3, 5]),
    TaskDef(5, "생략", None, None, predecessors=[1]),
]
TASKS = schedule(LAUNCH, DEFS, CAL)
T = {t.no: t for t in TASKS}


def sig(inputs, as_of, fixed=()):
    exp = expect(TASKS, inputs, CAL)
    return {no: judge(exp[no], inputs.get(no) or {}, as_of, 3, LAUNCH, no in fixed, CAL)["signal"] for no in T}, exp


def test_no_input_keeps_baseline():
    exp = expect(TASKS, {}, CAL)
    for no in (1, 2, 3, 4):
        assert (exp[no]["expected_start"], exp[no]["expected_end"], exp[no]["delay"]) == (T[no].start, T[no].end, 0)
    assert exp[5]["active"] is False


def test_delay_pushes_tight_successors_and_is_absorbed_by_float():
    late = CAL.add(T[1].end, 3)
    exp = expect(TASKS, {1: {"state": "예정변경", "change_date": late}}, CAL)
    assert exp[1]["delay"] == 3
    assert exp[2]["push"] == 3 and exp[2]["expected_end"] == CAL.add(T[2].end, 3)  # 여유 없음 → 그대로 밀림
    assert exp[3]["push"] == 3 and exp[3]["expected_end"] == CAL.add(T[3].end, 3)
    assert exp[4]["push"] == 3  # 2를 거쳐 출시까지 밀림 (3 → 4 는 여유 5로 흡수)
    s = product_signal([{"signal": "빨강", "expected_end": v["expected_end"]} for v in exp.values()], LAUNCH, CAL)
    assert (s["launch_impact_days"], s["expected_launch"], s["signal"]) == (3, CAL.add(LAUNCH, 3), "빨강")


def test_float_absorbs_delay():
    late = CAL.add(T[3].end, 4)  # 3 → 4 여유 5영업일 안
    signals, exp = sig({3: {"state": "예정변경", "change_date": late}}, T[1].start)
    assert exp[4]["push"] == 0 and exp[4]["expected_end"] == LAUNCH
    assert signals[3] == "노랑" and signals[4] == "초록"  # 늦지만 흡수됨
    assert product_signal([{"signal": signals[n], "expected_end": exp[n]["expected_end"]} for n in T],
                          LAUNCH, CAL)["signal"] == "초록"


def test_actual_beats_change_date_and_early_finish_does_not_pull():
    early = CAL.sub(T[1].end, 2)
    exp = expect(TASKS, {1: {"actual_end": early, "change_date": CAL.add(T[1].end, 9)}}, CAL)
    assert exp[1]["expected_end"] == early and exp[1]["delay"] == -2
    assert exp[2]["expected_start"] == T[2].start  # 기준일정은 앞당기지 않는다


def test_na_task_passes_predecessor_delay_through():
    defs = [TaskDef(1, "가", 20, 5), TaskDef(2, "나", 15, 5, predecessors=[1]), TaskDef(3, "다", 10, 5, predecessors=[2])]
    tasks = schedule(LAUNCH, defs, CAL)
    exp = expect(tasks, {1: {"change_date": CAL.add(tasks[0].end, 2)}, 2: {"state": "해당없음"}}, CAL)
    assert exp[2]["active"] is False
    assert exp[3]["push"] == 0  # 1 종료 → 3 착수 사이 5영업일 여유가 2일 지연을 흡수
    exp = expect(tasks, {1: {"change_date": CAL.add(tasks[0].end, 7)}, 2: {"state": "해당없음"}}, CAL)
    assert exp[3]["push"] == 2


def test_signals():
    before = T[1].start
    s, _ = sig({1: {"actual_end": CAL.add(T[1].end, 4)}, 3: {"state": "해당없음"}}, before)
    assert s[1] == "회색" and s[3] == "회색"            # 완료(늦게 끝나도)·해당 없음
    assert s[5] == "확인 필요"                           # 값 없는 Task
    s, _ = sig({}, CAL.add(T[1].end, 1))
    assert s[1] == "빨강"                                # 예상 종료 지남·미완료
    s, _ = sig({1: {"change_date": CAL.add(T[1].end, 5)}}, CAL.add(T[1].end, 1))
    assert s[1] == "노랑"                                # 변경 예정일이 아직 안 지남 → 빨강 아님
    assert s[4] == "빨강"                                # 출시일을 넘김
    s, _ = sig({3: {"change_date": CAL.add(T[3].end, 1)}}, before, fixed={3})
    assert s[3] == "빨강"                                # 고정일 Task는 밀리면 즉시 빨강
    s, _ = sig({}, CAL.sub(T[1].end, 3))
    assert s[1] == "노랑" and s[2] == "초록"             # 남은 여유 ≤ 기준값
    s, _ = sig({1: {"state": "완료", "estimated": True}}, date(2027, 3, 20))
    assert s[1] == "회색"                                # 완료일 모르는 완료


def test_infer_done_from_finished_successor():
    got = infer_done(TASKS, {2: {"state": "완료", "estimated": True}, 3: {"change_date": date(2027, 3, 1)}})
    assert got[1] == {"state": "완료", "estimated": True, "inferred": True}  # 2가 끝났으면 1도 끝남
    assert got[3] == {"change_date": date(2027, 3, 1)} and 4 not in got and 5 not in got
    x = expect(TASKS, got, CAL)[1]
    assert judge(x, got[1], date(2027, 3, 20), 3, LAUNCH, False, CAL)["reason"] == "완료 (후행 Task 완료로 추정)"


def test_cycle_is_error():
    defs = [TaskDef(1, "가", 10, 5, predecessors=[2]), TaskDef(2, "나", 5, 5, predecessors=[1])]
    with pytest.raises(ValueError, match="돌고"):
        expect(schedule(LAUNCH, defs, CAL), {}, CAL)


def test_past_change_date_counts_as_done():
    from app.engine.linked import past_as_done

    as_of = date(2026, 11, 24)
    inputs = {1: {"state": "예정변경", "change_date": date(2026, 11, 11)},   # 지남 → 완료
              2: {"state": "예정변경", "change_date": as_of},                # 오늘 → 그대로 예정
              3: {"state": "예정변경", "change_date": date(2026, 12, 1)},    # 앞으로 → 그대로 예정
              4: {"state": "해당없음"},
              5: {"state": "완료", "actual_end": date(2026, 11, 1), "change_date": date(2026, 11, 5)}}
    got = past_as_done(inputs, as_of)
    assert got[1] == {"state": "완료", "change_date": date(2026, 11, 11), "actual_end": date(2026, 11, 11),
                      "estimated": False, "from_past": True}
    assert got[2] == inputs[2] and got[3] == inputs[3] and got[4] == inputs[4] and got[5] == inputs[5]
    assert inputs[1]["state"] == "예정변경"  # 원본은 바꾸지 않음
    x = {"active": True, "expected_end": date(2026, 11, 11), "delay": 2}
    r = judge(x, got[1], as_of, 3, LAUNCH, False, CAL)
    assert (r["signal"], r["reason"]) == ("회색", "완료 (지난 예정일 11/11을 완료일로 봄) · 기준보다 2영업일 늦음")


def test_excluded_task_is_not_judged_until_input_arrives():
    from app.engine.linked import excluded_reason

    assert excluded_reason(None) is None and excluded_reason("엑셀") is None and excluded_reason("앱") is None
    why = excluded_reason("없음")
    assert why == "입력처 없음 — 판정 제외" and "디자인 시트" in excluded_reason("디자인 시트")
    late = CAL.add(T[1].end, 1)
    exp = expect(TASKS, {}, CAL)
    assert judge(exp[1], {}, late, 3, LAUNCH, False, CAL, why) == {"signal": "확인 필요", "slack": None, "reason": why}
    assert judge(exp[1], {}, late, 3, LAUNCH, False, CAL)["signal"] == "빨강"  # 지정 안 함 → 예전처럼 판정
    i = {"state": "예정변경", "change_date": CAL.add(T[1].end, 3)}  # 입력이 들어오면 판정
    exp = expect(TASKS, {1: i}, CAL)
    assert judge(exp[1], i, late, 3, LAUNCH, False, CAL, why)["signal"] == "노랑"
    done = {"state": "완료", "estimated": True, "inferred": True}  # 완료 추정은 회색
    assert judge(expect(TASKS, {1: done}, CAL)[1], done, late, 3, LAUNCH, False, CAL, why)["signal"] == "회색"
    # 판정 제외 Task도 예상일은 계산해 후행에 지연을 넘긴다
    assert expect(TASKS, {1: i}, CAL)[2]["push"] == 3
