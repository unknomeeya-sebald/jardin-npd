"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/ui";
import { API } from "@/lib/api";
import { clearAuth, getToken } from "@/lib/auth";

/** 원본 화면 (Cloudflare Access 로그인 필요) */
const ORIGIN_URL = "https://jardin-npd.pages.dev/nb#A";
/** 처음 여는 보기: A 한 화면 · B 제품별 상세 · C 담당자별 · M 내 Task · F 순서도 */
const FIRST_VIEW = "A";

/**
 * 일정관리 — jardin-npd.pages.dev/nb 를 그대로 복제한 화면.
 * 원본 HTML(스타일·스크립트·데이터 내장)을 로그인한 사람에게만 백엔드가 내려주고,
 * 여기서는 blob 주소로 만들어 iframe에 띄운다. 고친 내용은 원본처럼 이 브라우저(localStorage)에 남는다.
 */
export default function SchedulePage() {
  const [src, setSrc] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let url: string | null = null;
    let alive = true;
    (async () => {
      const token = getToken();
      let r: Response;
      try {
        r = await fetch(`${API}/api/clone/npd-schedule`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          cache: "no-store",
        });
      } catch {
        if (alive) setErr(`백엔드(${API})에 연결할 수 없습니다. 백엔드 서버가 켜져 있는지 확인하세요.`);
        return;
      }
      if (r.status === 401) { clearAuth(); return; }
      if (!r.ok) {
        let msg = `${r.status}`;
        try { msg = (await r.json()).detail ?? msg; } catch {}
        if (alive) setErr(msg);
        return;
      }
      const html = await r.text();
      if (!alive) return;
      url = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
      setSrc(`${url}#${FIRST_VIEW}`);
    })();
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, []);

  return (
    <>
      <PageHeader
        title="일정관리"
        desc="NPD 일정(신제품 개발 일정 · 담당자 현황) 화면을 그대로 옮겼습니다. 고친 내용은 이 브라우저에만 저장되며, 정본 반영은 엑셀 내려받기로 합니다."
      >
        <a href={ORIGIN_URL} target="_blank" rel="noopener noreferrer"
           className="rounded-lg border border-line px-3 py-1.5 text-xs text-muted hover:text-ink">
          원본 열기 ↗
        </a>
      </PageHeader>

      {err && <p className="rounded-lg border border-line bg-surface p-4 text-sm text-bad">{err}</p>}
      {!err && !src && <p className="text-sm text-muted">일정관리 화면을 불러오는 중…</p>}
      {src && (
        <iframe
          title="일정관리"
          src={src}
          className="h-[calc(100vh-170px)] min-h-[640px] w-full rounded-xl border border-line bg-white"
        />
      )}
    </>
  );
}
