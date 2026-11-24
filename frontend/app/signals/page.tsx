"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useApp } from "@/components/AppContext";
import { Empty, PageHeader, Panel, SignalBar, SignalChip, countSignals } from "@/components/ui";
import { api, type Schedule } from "@/lib/api";

export default function SignalsPage() {
  const { products, asOf, sched, setActiveId, setError, settings } = useApp();
  const [all, setAll] = useState<Schedule[]>([]);

  useEffect(() => {
    let alive = true;
    Promise.all(products.map((p) => api.schedule(p.id, asOf)))
      .then((r) => alive && setAll(r))
      .catch((e: Error) => alive && setError(e.message));
    return () => { alive = false; };
  }, [products, asOf, sched, setError]);

  const focus = (sched?.tasks.filter((t) => t.signal === "빨강" || t.signal === "노랑") ?? [])
    .sort((a, b) => (a.signal === b.signal ? a.no - b.no : a.signal === "빨강" ? -1 : 1));
  const th = settings.yellow_threshold?.value ?? "?";

  return (
    <>
      <PageHeader
        title="신호등 현황"
        desc={<>완료·해당 없음은 회색입니다. 예상 종료일이 지났는데 미완료이거나, 고정일 Task가 밀리거나, 예상 종료가 출시일을 넘으면 빨강, 기준보다 늦지만 출시일 안이거나 여유가 {th}영업일 이하이면 노랑, 그 외는 초록입니다. 입력처가 없는 Task(입력 원천이 엑셀·앱이 아님)는 입력이 들어오기 전까지 판정에서 빼고 「확인 필요」로 둡니다. 예상 종료일은 실적·변경 예정일과 선행 Task 지연을 반영한 날짜입니다.</>}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {all.map((s) => {
          const c = countSignals(s.tasks);
          const active = sched?.product.id === s.product.id;
          return (
            <button key={s.product.id} onClick={() => setActiveId(s.product.id)} aria-pressed={active}
                    className={`panel p-5 text-left transition-colors hover:border-line-strong ${active ? "!border-accent ring-1 ring-accent" : ""}`}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[15px] font-semibold text-ink">{s.product.name}</span>
                <span className="num text-xs text-muted">{s.product.launch_date} 출시</span>
              </div>
              <div className="mt-3 flex items-baseline gap-1.5">
                <span className={`num text-3xl font-semibold tracking-[-0.03em] ${c["빨강"] ? "text-bad" : "text-ink"}`}>{c["빨강"]}</span>
                <span className="text-[13px] text-muted">건 지연</span>
              </div>
              {s.summary && (
                <p className={`mt-2 text-xs ${s.summary.launch_impact_days > 0 ? "font-medium text-bad" : "text-muted"}`}>
                  {s.summary.launch_impact_days > 0
                    ? <>예상 출시 <span className="num">{s.summary.expected_launch}</span> · 출시 영향 +{s.summary.launch_impact_days}영업일</>
                    : "출시 영향 없음"}
                </p>
              )}
              <SignalBar counts={c} className="mt-4" />
            </button>
          );
        })}
      </div>

      <Panel pad={false} title={<>{sched?.product.name} 주의할 Task <span className="num ml-1 font-normal text-muted">{focus.length}건</span></>}
             aside={<Link href="/gantt" className="btn-quiet">간트에서 실적 입력</Link>}>
        {focus.length === 0 ? <Empty title="빨강·노랑 Task가 없습니다">기준일을 바꾸거나 실적 완료일을 넣으면 다시 판정합니다.</Empty> : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>신호</th><th>No</th><th>Task</th><th>예정 종료</th><th>실적 완료</th><th>판정 근거</th></tr></thead>
              <tbody>
                {focus.map((t) => (
                  <tr key={t.no}>
                    <td><SignalChip s={t.signal} /></td>
                    <td className="num text-faint">{t.no}</td>
                    <td className="font-medium text-ink">{t.name}</td>
                    <td className="num">{t.end}</td>
                    <td className={`num ${t.actual_end ? "" : "text-faint"}`}>{t.actual_end ?? "미완료"}</td>
                    <td className="text-muted">{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}
