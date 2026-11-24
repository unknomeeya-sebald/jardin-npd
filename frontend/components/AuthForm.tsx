"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { ThemeSwitch } from "@/components/Sidebar";
import { api } from "@/lib/api";
import { safeNext, saveAuth } from "@/lib/auth";

type Mode = "login" | "signup";

const TEXT: Record<Mode, { title: string; sub: string; submit: string; busy: string; alt: string; altLink: string; altHref: string }> = {
  login: {
    title: "로그인", sub: "등록한 이메일과 비밀번호를 입력하세요.", submit: "로그인", busy: "로그인 중…",
    alt: "계정이 없나요?", altLink: "회원가입", altHref: "/signup",
  },
  signup: {
    title: "회원가입", sub: "가입하면 바로 로그인됩니다.", submit: "가입하기", busy: "가입 중…",
    alt: "이미 계정이 있나요?", altLink: "로그인", altHref: "/login",
  },
};

export default function AuthForm({ mode }: { mode: Mode }) {
  const t = TEXT[mode];
  const next = safeNext(useSearchParams().get("next"));
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const pwRule = /[A-Za-z]/.test(pw) && /\d/.test(pw) && pw.length >= 8;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (mode === "signup") {
      if (!pwRule) return setErr("비밀번호는 8자 이상, 영문과 숫자를 모두 포함해야 합니다.");
      if (pw !== pw2) return setErr("비밀번호 확인이 일치하지 않습니다.");
    }
    setBusy(true);
    try {
      const r = mode === "login"
        ? await api.login({ email, password: pw })
        : await api.signup({ email, name, password: pw });
      saveAuth(r.token, r.user); // AppShell이 next 경로로 보낸다
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <AuthFrame>
        <form onSubmit={submit} className="panel space-y-4 p-6" noValidate>
          <div>
            <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-ink">{t.title}</h1>
            <p className="mt-1 text-[13px] text-muted">{t.sub}</p>
          </div>

          <Input label="이메일" type="email" autoComplete="email" value={email} onChange={setEmail} autoFocus />
          {mode === "signup" && <Input label="이름" autoComplete="name" value={name} onChange={setName} maxLength={50} />}
          <Input label="비밀번호" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"}
                 value={pw} onChange={setPw}
                 hint={mode === "signup" ? <span className={pw && !pwRule ? "text-warn" : ""}>8자 이상, 영문과 숫자 포함</span> : undefined} />
          {mode === "signup" && (
            <Input label="비밀번호 확인" type="password" autoComplete="new-password" value={pw2} onChange={setPw2}
                   hint={pw2 && pw !== pw2 ? <span className="text-bad">일치하지 않습니다</span> : undefined} />
          )}

          {err && <p role="alert" className="rounded-lg bg-bad-soft px-3 py-2 text-[13px] text-bad">{err}</p>}

          <button className="btn w-full" disabled={busy || !email || !pw || (mode === "signup" && (!name.trim() || !pw2))}>
            {busy ? t.busy : t.submit}
          </button>

          <p className="text-center text-[13px] text-muted">
            {t.alt}{" "}
            <Link href={next === "/gantt" ? t.altHref : `${t.altHref}?next=${encodeURIComponent(next)}`}
                  className="font-semibold text-accent underline-offset-2 hover:underline">{t.altLink}</Link>
          </p>
          {mode === "login" && (
            <p className="text-center text-[13px] text-muted">
              <Link href="/forgot" className="font-semibold text-accent underline-offset-2 hover:underline">비밀번호를 잊으셨나요?</Link>
            </p>
          )}
        </form>
    </AuthFrame>
  );
}

/** 로그인·회원가입·비밀번호 찾기 화면의 공통 틀(로고 + 테마 전환) */
export function AuthFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-5 py-12">
      <div className="w-full max-w-[380px]">
        <div className="mb-7 flex items-center gap-2.5">
          <svg viewBox="0 0 32 32" className="h-9 w-9" aria-hidden>
            <rect width="32" height="32" rx="9" className="fill-accent" />
            <rect x="6" y="9" width="14" height="3" rx="1.5" className="fill-accent-ink" opacity="0.55" />
            <rect x="11" y="14.5" width="11" height="3" rx="1.5" className="fill-accent-ink" opacity="0.8" />
            <rect x="16" y="20" width="8" height="3" rx="1.5" className="fill-accent-ink" />
            <rect x="25.5" y="7" width="1.6" height="18" rx="0.8" className="fill-accent-ink" />
          </svg>
          <div className="leading-tight">
            <div className="text-[15px] font-semibold tracking-[-0.01em] text-ink">NPD 일정 관리</div>
            <div className="text-[11px] text-faint">출시일에서 거꾸로 짜는 일정</div>
          </div>
        </div>

        {children}

        <div className="mx-auto mt-6 max-w-[240px]"><ThemeSwitch /></div>
      </div>
    </div>
  );
}

export function Input({ label, value, onChange, hint, ...rest }: {
  label: string; value: string; onChange: (v: string) => void; hint?: React.ReactNode;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted">{label}</span>
      <input {...rest} className="input h-10" value={value} onChange={(e) => onChange(e.target.value)} />
      {hint && <span className="text-[11px] text-faint">{hint}</span>}
    </label>
  );
}
