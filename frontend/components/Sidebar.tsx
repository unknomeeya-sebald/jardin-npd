"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useApp } from "@/components/AppContext";
import { setTheme, useThemePref, type ThemePref } from "@/components/theme";
import { clearAuth, useAuth } from "@/lib/auth";

type App = ReturnType<typeof useApp>;
type Item = { href: string; label: string; icon: string; badge?: (a: App) => { n: number; tone: "bad" | "warn" } | null };
type Group = { title: string; items: Item[] };

// 24x24 stroke 아이콘
const I = {
  gantt: "M4 6h9M7 12h11M4 18h6M16 6h4M13 18h7",
  absorb: "M4 7h16M7 12h10M10 17h4",
  signal: "M12 3.5a2 2 0 110 4 2 2 0 010-4zM12 10a2 2 0 110 4 2 2 0 010-4zM12 16.5a2 2 0 110 4 2 2 0 010-4z",
  overlap: "M3.5 8.5h11v7h-11zM9.5 5h11v7",
  product: "M4 7.5l8-4 8 4v9l-8 4-8-4zM4 7.5l8 4 8-4M12 11.5v9",
  task: "M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01",
  holiday: "M4 6h16v14H4zM4 10.5h16M8.5 3.5v4M15.5 3.5v4",
  calendar: "M4 6h16v14H4zM4 10.5h16M8.5 3.5v4M15.5 3.5v4M8 14h3M8 17h6",
  settings: "M4 7h10M18 7h2M4 17h4M12 17h8M14 4.5v5M8 14.5v5",
  sun: "M12 8a4 4 0 100 8 4 4 0 000-8zM12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4",
  moon: "M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z",
  system: "M3.5 5h17v11h-17zM8.5 20h7M12 16v4",
  action: "M9 11.5l2.2 2.2L15.5 9.5M4.5 4.5h15v15h-15z",
  logout: "M14 4.5h4.5v15H14M10 8l-4 4 4 4M6 12h10",
};

export const MENU: Group[] = [
  {
    title: "일정",
    items: [
      { href: "/gantt", label: "간트 타임라인", icon: I.gantt },
      { href: "/absorb", label: "지연 흡수", icon: I.absorb },
      { href: "/schedule", label: "일정관리", icon: I.calendar },
    ],
  },
  {
    title: "모니터링",
    items: [
      { href: "/signals", label: "신호등 현황", icon: I.signal, badge: (a) => (a.sched?.red_count ? { n: a.sched.red_count, tone: "bad" } : null) },
      { href: "/concurrent", label: "동시 진행", icon: I.overlap },
      { href: "/actions", label: "Action Item", icon: I.action },
    ],
  },
  {
    title: "기준 데이터",
    items: [
      { href: "/products", label: "제품 관리", icon: I.product },
      { href: "/tasks", label: "Task 기준", icon: I.task, badge: (a) => (a.health?.tasks_needing_check ? { n: a.health.tasks_needing_check, tone: "warn" } : null) },
      { href: "/holidays", label: "공휴일", icon: I.holiday },
    ],
  },
  {
    title: "설정",
    items: [{ href: "/settings", label: "판정·흡수 설정", icon: I.settings }],
  },
];

export function pageTitle(path: string): { group: string; label: string } | undefined {
  for (const g of MENU) for (const it of g.items) if (path.startsWith(it.href)) return { group: g.title, label: it.label };
}

function Icon({ d, className = "h-[18px] w-[18px]" }: { d: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={`shrink-0 ${className}`} fill="none" stroke="currentColor" strokeWidth={1.7}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={d} />
    </svg>
  );
}

export default function Sidebar() {
  const path = usePathname();
  const app = useApp();
  return (
    <aside className="hidden w-[232px] shrink-0 border-r border-line bg-surface md:block">
     <div className="sticky top-0 flex h-screen flex-col">
      <div className="flex items-center gap-2.5 px-5 pb-5 pt-6">
        <Mark />
        <div className="leading-tight">
          <div className="text-[15px] font-semibold tracking-[-0.01em] text-ink">NPD 일정 관리</div>
          <div className="text-[11px] text-faint">출시일에서 거꾸로 짜는 일정</div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3" aria-label="주 메뉴">
        {MENU.map((g) => (
          <div key={g.title} className="mb-5">
            <div className="px-3 pb-1.5 text-xs font-medium text-faint">{g.title}</div>
            <ul className="space-y-0.5">
              {g.items.map((it) => {
                const active = path.startsWith(it.href);
                const badge = it.badge?.(app);
                return (
                  <li key={it.href}>
                    <Link href={it.href} aria-current={active ? "page" : undefined}
                          className={`group relative flex h-9 items-center gap-3 rounded-lg px-3 text-[13.5px] transition-colors ${
                            active ? "bg-accent-soft font-semibold text-accent" : "text-muted hover:bg-sunken hover:text-ink"}`}>
                      {active && <span aria-hidden className="absolute -left-3 top-2 bottom-2 w-[3px] rounded-r-full bg-accent" />}
                      <Icon d={it.icon} />
                      <span className="flex-1 truncate">{it.label}</span>
                      {badge && (
                        <span className={`num min-w-5 rounded-full px-1.5 text-center text-[11px] font-semibold leading-5 ${
                          badge.tone === "bad" ? "bg-bad text-white dark:text-bg" : "bg-warn-soft text-warn"}`}>{badge.n}</span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="space-y-3 border-t border-line px-4 py-4">
        <UserBox />
        <ThemeSwitch />
        <div className="flex items-center gap-2 px-1 text-[11px] text-faint">
          <span className={`h-1.5 w-1.5 rounded-full ${app.health?.db === "postgres" ? "bg-ok" : app.health ? "bg-warn" : "bg-none"}`} />
          {app.health ? (app.health.db === "postgres" ? "Supabase 연결됨" : "로컬 DB(SQLite) 사용 중") : "서버 확인 중"}
        </div>
      </div>
     </div>
    </aside>
  );
}

function Mark() {
  // 출시일(세로선)을 향해 줄어드는 막대 — 역산 일정의 형태
  return (
    <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden>
      <rect width="32" height="32" rx="9" className="fill-accent" />
      <rect x="6" y="9" width="14" height="3" rx="1.5" className="fill-accent-ink" opacity="0.55" />
      <rect x="11" y="14.5" width="11" height="3" rx="1.5" className="fill-accent-ink" opacity="0.8" />
      <rect x="16" y="20" width="8" height="3" rx="1.5" className="fill-accent-ink" />
      <rect x="25.5" y="7" width="1.6" height="18" rx="0.8" className="fill-accent-ink" />
    </svg>
  );
}

function UserBox() {
  const auth = useAuth();
  if (!auth) return null;
  const { user } = auth;
  return (
    <div className="flex items-center gap-2.5 px-1">
      <span aria-hidden className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[13px] font-semibold text-accent">
        {user.name.slice(0, 1)}
      </span>
      <div className="min-w-0 flex-1 leading-tight">
        <div className="truncate text-[13px] font-medium text-ink">{user.name}</div>
        <div className="truncate text-[11px] text-faint">{user.email}</div>
      </div>
      <button onClick={clearAuth} title="로그아웃" aria-label="로그아웃"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-faint transition-colors hover:bg-sunken hover:text-ink">
        <Icon d={I.logout} className="h-4 w-4" />
      </button>
    </div>
  );
}

const THEMES: { v: ThemePref; label: string; icon: string }[] = [
  { v: "light", label: "밝게", icon: I.sun },
  { v: "dark", label: "어둡게", icon: I.moon },
  { v: "system", label: "시스템", icon: I.system },
];

export function ThemeSwitch() {
  const pref = useThemePref();
  return (
    <div role="radiogroup" aria-label="화면 테마" className="grid grid-cols-3 gap-0.5 rounded-lg bg-sunken p-0.5">
      {THEMES.map((t) => {
        const on = pref === t.v;
        return (
          <button key={t.v} role="radio" aria-checked={on} onClick={() => setTheme(t.v)} title={`${t.label} 모드`}
                  className={`flex h-7 items-center justify-center gap-1 rounded-md text-[11px] font-medium transition ${
                    on ? "bg-raised text-ink shadow-panel" : "text-faint hover:text-ink"}`}>
            <Icon d={t.icon} className="h-3.5 w-3.5" />
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
