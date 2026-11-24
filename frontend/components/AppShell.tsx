"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { AppProvider, useApp } from "@/components/AppContext";
import Sidebar, { MENU, pageTitle } from "@/components/Sidebar";
import { Notice } from "@/components/ui";
import { bizBetween } from "@/lib/dates";
import { clearAuth, safeNext, useAuth } from "@/lib/auth";

/** 로그인 없이 볼 수 있는 경로 */
export const PUBLIC_PATHS = ["/login", "/signup", "/forgot"];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const next = useSearchParams().get("next");
  const auth = useAuth(); // undefined = 아직 모름(서버 렌더·하이드레이션)
  const isPublic = PUBLIC_PATHS.some((p) => path.startsWith(p));

  useEffect(() => {
    if (auth === null && !isPublic) router.replace(`/login?next=${encodeURIComponent(path)}`);
    if (auth && isPublic) router.replace(safeNext(next));
  }, [auth, isPublic, path, next, router]);

  if (isPublic) return auth ? null : <>{children}</>;
  if (auth === null) return <p className="p-8 text-sm text-muted">로그인 페이지로 이동합니다…</p>;
  return <Authed>{children}</Authed>;
}

function Authed({ children }: { children: React.ReactNode }) {
  return (
    <AppProvider>
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <MobileNav />
          <Alerts />
          <main className="mx-auto w-full max-w-[1680px] min-w-0 flex-1 space-y-6 px-5 pb-12 pt-6 md:px-8">{children}</main>
        </div>
      </div>
    </AppProvider>
  );
}

/** 출시까지 남은 영업일·D-주차 (C-02: 영업일 ÷ 5 올림) */
export function useCountdown() {
  const { sched, asOf, holidays } = useApp();
  if (!sched) return null;
  const launch = sched.product.launch_date;
  const days = bizBetween(asOf, launch, holidays);
  const weeks = days >= 0 ? Math.ceil(days / 5) : -Math.ceil(-days / 5);
  return { launch, days, weeks, label: days >= 0 ? `D-${weeks}주` : `D+${-weeks}주` };
}

function TopBar() {
  const path = usePathname();
  const { products, activeId, setActiveId, asOf, setAsOf } = useApp();
  const t = pageTitle(path);
  const cd = useCountdown();
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-bg/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1680px] flex-wrap items-center justify-between gap-3 px-5 py-3 md:px-8">
        <div className="flex items-center gap-1.5 text-[13px]">
          {t && <><span className="text-faint">{t.group}</span><span className="text-faint">/</span><span className="font-medium text-ink">{t.label}</span></>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {cd && (
            <div className="hidden items-baseline gap-1.5 rounded-lg px-2 sm:flex" title={`기준일부터 출시일(${cd.launch})까지 영업일`}>
              <span className={`num text-sm font-semibold ${cd.days < 0 ? "text-bad" : "text-ink"}`}>{cd.label}</span>
              <span className="num text-xs text-muted">{cd.days >= 0 ? `${cd.days}영업일 남음` : `${-cd.days}영업일 지남`}</span>
            </div>
          )}
          <select aria-label="대상 제품" className="input min-w-44 font-medium" value={activeId ?? ""}
                  onChange={(e) => setActiveId(Number(e.target.value))}>
            {products.map((p) => <option key={p.id} value={p.id}>{p.name}  ({p.launch_date} 출시)</option>)}
          </select>
          <label className="flex items-center gap-2">
            <span className="text-xs text-muted">기준일</span>
            <input type="date" aria-label="기준일" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="input" />
          </label>
        </div>
      </div>
    </header>
  );
}

function MobileNav() {
  const path = usePathname();
  return (
    <nav aria-label="주 메뉴(모바일)" className="flex gap-1 overflow-x-auto border-b border-line bg-surface px-4 py-2 md:hidden">
      {MENU.flatMap((g) => g.items).map((it) => (
        <Link key={it.href} href={it.href}
              className={`whitespace-nowrap rounded-full px-3 py-1 text-xs ${path.startsWith(it.href) ? "bg-accent-soft font-semibold text-accent" : "text-muted"}`}>
          {it.label}
        </Link>
      ))}
      <button onClick={clearAuth} className="ml-auto whitespace-nowrap rounded-full px-3 py-1 text-xs text-muted hover:text-ink">로그아웃</button>
    </nav>
  );
}

function Alerts() {
  const { sched, absorbAlert, error, health } = useApp();
  const items: React.ReactNode[] = [];
  if (absorbAlert) items.push(<Notice key="absorb" tone="bad"><AlertIcon /><span><b>지연 알림</b> {absorbAlert.replace(/^지연 알림:\s*/, "")}</span></Notice>);
  if (sched && sched.red_count > 0)
    items.push(
      <Notice key="red" tone="bad">
        <AlertIcon />
        <span>
          <b>지연 알림</b> {sched.product.name}에 빨강 Task가 {sched.red_count}건 있습니다.{" "}
          <Link href="/signals" className="font-semibold underline underline-offset-2">신호등 현황 보기</Link>
        </span>
      </Notice>,
    );
  if (error) items.push(<Notice key="err" tone="bad"><AlertIcon /><span><b>오류</b> {error}</span></Notice>);
  if (health && health.tasks_needing_check > 0)
    items.push(
      <Notice key="check" tone="warn">
        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-warn" />
        <span>
          Task {health.tasks_needing_check}개는 착수 역산일수·소요일수가 비어 있어 막대를 그리지 못합니다.{" "}
          <Link href="/tasks" className="font-semibold text-accent underline underline-offset-2">엑셀·CSV 기준 가져오기</Link>
        </span>
      </Notice>,
    );
  if (!items.length) return null;
  return <div className="mx-auto w-full max-w-[1680px] space-y-2 px-5 pt-5 md:px-8">{items}</div>;
}

function AlertIcon() {
  return (
    <svg viewBox="0 0 24 24" className="mt-0.5 h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden>
      <path d="M12 4l9 16H3zM12 10v4M12 17h.01" />
    </svg>
  );
}
