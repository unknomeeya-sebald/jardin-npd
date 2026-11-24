"use client";

import Link from "next/link";
import { useState } from "react";
import { AuthFrame, Input } from "@/components/AuthForm";
import { api } from "@/lib/api";
import { saveAuth } from "@/lib/auth";

/** 비밀번호 찾기: ① 이메일 → Slack DM으로 인증 코드 ② 코드 + 새 비밀번호 */
export default function ForgotForm() {
  const [step, setStep] = useState<1 | 2>(1);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [ttl, setTtl] = useState(10);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const pwRule = /[A-Za-z]/.test(pw) && /\d/.test(pw) && pw.length >= 8;

  async function sendCode() {
    setErr(null);
    setInfo(null);
    setBusy(true);
    try {
      const r = await api.forgot({ email });
      setTtl(r.ttl_min);
      if (step === 2) setInfo("인증 코드를 다시 보냈습니다.");
      setStep(2);
    } catch (e) {
      setErr((e as Error).message);
    }
    setBusy(false);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (step === 1) return sendCode();
    setErr(null);
    setInfo(null);
    if (!pwRule) return setErr("비밀번호는 8자 이상, 영문과 숫자를 모두 포함해야 합니다.");
    if (pw !== pw2) return setErr("비밀번호 확인이 일치하지 않습니다.");
    setBusy(true);
    try {
      const r = await api.resetPassword({ email, code, password: pw });
      saveAuth(r.token, r.user); // AppShell이 앱 화면으로 보낸다
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <AuthFrame>
      <form onSubmit={submit} className="panel space-y-4 p-6" noValidate>
        <div>
          <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-ink">비밀번호 찾기</h1>
          <p className="mt-1 text-[13px] text-muted">
            {step === 1
              ? "가입한 이메일을 입력하면 본인 Slack 개인 메시지(DM)로 인증 코드를 보냅니다."
              : `Slack DM으로 받은 6자리 인증 코드와 새 비밀번호를 입력하세요. 코드는 ${ttl}분 동안 유효합니다.`}
          </p>
        </div>

        <Input label="이메일" type="email" autoComplete="email" value={email} onChange={setEmail}
               autoFocus={step === 1} readOnly={step === 2} />
        {step === 2 && (
          <>
            <Input label="인증 코드" inputMode="numeric" autoComplete="one-time-code" maxLength={6}
                   value={code} onChange={(v) => setCode(v.replace(/\D/g, ""))} autoFocus />
            <Input label="새 비밀번호" type="password" autoComplete="new-password" value={pw} onChange={setPw}
                   hint={<span className={pw && !pwRule ? "text-warn" : ""}>8자 이상, 영문과 숫자 포함</span>} />
            <Input label="새 비밀번호 확인" type="password" autoComplete="new-password" value={pw2} onChange={setPw2}
                   hint={pw2 && pw !== pw2 ? <span className="text-bad">일치하지 않습니다</span> : undefined} />
          </>
        )}

        {err && <p role="alert" className="rounded-lg bg-bad-soft px-3 py-2 text-[13px] text-bad">{err}</p>}
        {info && <p role="status" className="rounded-lg bg-accent-soft px-3 py-2 text-[13px] text-accent">{info}</p>}

        <button className="btn w-full" disabled={busy || !email || (step === 2 && (code.length !== 6 || !pw || !pw2))}>
          {busy ? "처리 중…" : step === 1 ? "인증 코드 받기" : "비밀번호 바꾸고 로그인"}
        </button>

        <p className="text-center text-[13px] text-muted">
          {step === 2 && (
            <>
              <button type="button" onClick={sendCode} disabled={busy}
                      className="font-semibold text-accent underline-offset-2 hover:underline">코드 다시 받기</button>
              <span className="mx-2 text-faint">·</span>
            </>
          )}
          <Link href="/login" className="font-semibold text-accent underline-offset-2 hover:underline">로그인으로 돌아가기</Link>
        </p>
      </form>
    </AuthFrame>
  );
}
