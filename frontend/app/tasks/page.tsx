"use client";

import { useEffect, useState } from "react";
import { useApp } from "@/components/AppContext";
import { Metric, PageHeader, Panel } from "@/components/ui";
import { api, type TaskBase } from "@/lib/api";

export default function TasksPage() {
  const { baseVer, run, reloadBase, setError } = useApp();
  const [tasks, setTasks] = useState<TaskBase[]>([]);

  useEffect(() => {
    let alive = true;
    api.tasks().then((r) => alive && setTasks(r)).catch((e: Error) => alive && setError(e.message));
    return () => { alive = false; };
  }, [baseVer, setError]);

  const missing = tasks.filter((t) => t.start_offset == null || t.duration == null).length;
  return (
    <>
      <PageHeader title="Task 기준" desc="엑셀(NB Scheduling)에서 옮긴 기준 데이터입니다. 화면에서는 고치지 않고 파일(엑셀·CSV) 가져오기로만 바꿉니다. 단위는 영업일입니다.">
        <label className="btn cursor-pointer">
          엑셀·CSV 가져오기
          <input type="file" accept=".xlsx,.xlsm,.csv" className="sr-only" onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            if (!confirm(`Task 기준 데이터 전체와 입력한 실적이 「${f.name}」 내용으로 바뀝니다. 계속할까요?`)) { e.target.value = ""; return; }
            const r = await run(() => api.importTasks(f));
            if (r) { alert(`Task ${r.imported}개를 가져왔습니다.`); reloadBase(); }
            e.target.value = "";
          }} />
        </label>
      </PageHeader>

      <Panel pad={false}>
        <div className="grid grid-cols-3 gap-6 border-b border-line p-6">
          <Metric label="전체 Task" value={tasks.length} unit="개" />
          <Metric label="값 있음" value={tasks.length - missing} unit="개" tone="ok" />
          <Metric label="확인 필요" value={missing} unit="개" tone={missing ? "warn" : undefined} />
        </div>
        <div className="max-h-[62vh] overflow-auto">
          <table className="tbl">
            <thead className="sticky top-0 bg-surface">
              <tr><th>No</th><th>Task</th><th>단계</th><th className="text-right">착수 역산</th><th className="text-right">소요</th><th className="text-right">완료 역산</th><th>기준</th><th>선행</th><th>비고</th></tr>
            </thead>
            <tbody>
              {tasks.map((t) => {
                const miss = t.start_offset == null || t.duration == null;
                return (
                  <tr key={t.no} className={miss ? "text-faint" : ""}>
                    <td className="num">{t.no}</td>
                    <td className={miss ? "" : "font-medium text-ink"}>{t.name}</td>
                    <td>{t.phase ?? <span className="text-faint">미지정</span>}</td>
                    <td className="num text-right">{t.start_offset ?? "–"}</td>
                    <td className="num text-right">{t.duration ?? "–"}</td>
                    <td className="num text-right font-medium">{miss ? "–" : t.start_offset! - t.duration!}</td>
                    <td>{t.basis === "착수" ? <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-semibold text-accent">착수</span> : t.basis}</td>
                    <td className="num">{t.predecessors ?? "–"}</td>
                    <td className="max-w-[28ch] truncate text-xs text-muted" title={t.note ?? ""}>{t.note}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="border-t border-line px-6 py-3 text-xs text-faint">엑셀(.xlsx)·CSV 첫 줄 열 제목: no, name, phase, start_offset, duration, basis, predecessors, buffer_days, note (no·name 필수, 화면의 한글 제목 No·Task·단계·착수 역산·소요·기준·선행·비고도 가능)</p>
      </Panel>
    </>
  );
}
