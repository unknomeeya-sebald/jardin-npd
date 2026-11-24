import type { Signal } from "@/lib/api";

export const SIGNALS: Signal[] = ["초록", "노랑", "빨강", "회색", "확인 필요"];

export const SIGNAL_STYLE: Record<Signal, string> = {
  초록: "bg-ok",
  노랑: "bg-warn",
  빨강: "bg-bad",
  회색: "bg-faint",
  "확인 필요": "bg-none",
};

const SIGNAL_TEXT: Record<Signal, string> = {
  초록: "text-ok",
  노랑: "text-warn",
  빨강: "text-bad",
  회색: "text-faint",
  "확인 필요": "text-faint",
};

const SIGNAL_CHIP: Record<Signal, string> = {
  초록: "bg-ok-soft text-ok",
  노랑: "bg-warn-soft text-warn",
  빨강: "bg-bad-soft text-bad",
  회색: "bg-sunken text-muted",
  "확인 필요": "bg-sunken text-faint",
};

export function Field({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={`flex flex-col gap-1 ${className}`}>
      <span className="text-xs font-medium text-muted">{label}</span>
      {children}
    </label>
  );
}

export function PageHeader({ title, desc, children }: { title: string; desc?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold leading-tight tracking-[-0.01em] text-ink">{title}</h1>
        {desc && <p className="mt-1 max-w-[72ch] text-[13px] leading-relaxed text-muted">{desc}</p>}
      </div>
      {children && <div className="flex flex-wrap items-end gap-2">{children}</div>}
    </div>
  );
}

export function Panel({ title, aside, children, className = "", pad = true }: {
  title?: React.ReactNode; aside?: React.ReactNode; children: React.ReactNode; className?: string; pad?: boolean;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || aside) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
          {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
          {aside}
        </header>
      )}
      <div className={pad ? "p-5" : ""}>{children}</div>
    </section>
  );
}

/** 숫자 요약: 테두리 상자 대신 큰 숫자 + 작은 설명 */
export function Metric({ label, value, unit, tone }: { label: string; value: React.ReactNode; unit?: string; tone?: "bad" | "warn" | "ok" }) {
  const color = tone === "bad" ? "text-bad" : tone === "warn" ? "text-warn" : tone === "ok" ? "text-ok" : "text-ink";
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-0.5 flex items-baseline gap-1 ${color}`}>
        <span className="num text-2xl font-semibold tracking-[-0.02em]">{value}</span>
        {unit && <span className="text-xs text-muted">{unit}</span>}
      </div>
    </div>
  );
}

export function SignalDot({ s, size = "h-2.5 w-2.5" }: { s: Signal; size?: string }) {
  return <span aria-hidden className={`inline-block shrink-0 rounded-full ${size} ${SIGNAL_STYLE[s]}`} />;
}

export function SignalChip({ s }: { s: Signal }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold ${SIGNAL_CHIP[s]}`}>
      <SignalDot s={s} size="h-1.5 w-1.5" />
      {s}
    </span>
  );
}

/** 신호 분포 막대: 비율을 한 줄로 */
export function SignalBar({ counts, className = "" }: { counts: Record<Signal, number>; className?: string }) {
  const total = SIGNALS.reduce((a, s) => a + counts[s], 0) || 1;
  return (
    <div className={className}>
      <div className="flex h-2 overflow-hidden rounded-full bg-sunken" role="img"
           aria-label={SIGNALS.map((s) => `${s} ${counts[s]}`).join(", ")}>
        {SIGNALS.map((s) => counts[s] > 0 && (
          <span key={s} className={`${SIGNAL_STYLE[s]} h-full`} style={{ width: `${(counts[s] / total) * 100}%` }} />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {SIGNALS.map((s) => (
          <span key={s} className="flex items-center gap-1.5 text-muted">
            <SignalDot s={s} />
            {s}
            <b className={`num font-semibold ${counts[s] ? SIGNAL_TEXT[s] : "text-faint"}`}>{counts[s]}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

export function countSignals(tasks: { signal: Signal }[]): Record<Signal, number> {
  const c: Record<Signal, number> = { 초록: 0, 노랑: 0, 빨강: 0, 회색: 0, "확인 필요": 0 };
  tasks.forEach((t) => (c[t.signal] += 1));
  return c;
}

export function Empty({ title, children }: { title?: string; children?: React.ReactNode }) {
  return (
    <div className="px-6 py-10 text-center">
      {title && <p className="text-sm font-medium text-ink">{title}</p>}
      {children && <p className="mt-1 text-[13px] text-muted">{children}</p>}
    </div>
  );
}

export function Notice({ tone, children }: { tone: "bad" | "warn" | "info"; children: React.ReactNode }) {
  const cls = tone === "bad" ? "border-bad/30 bg-bad-soft text-bad" : tone === "warn" ? "border-warn/30 bg-warn-soft text-ink" : "border-accent/25 bg-accent-soft text-ink";
  return <div role={tone === "bad" ? "alert" : undefined} className={`flex items-start gap-2.5 rounded-xl border px-4 py-2.5 text-[13px] leading-relaxed ${cls}`}>{children}</div>;
}
