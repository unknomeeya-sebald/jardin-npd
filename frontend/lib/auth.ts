import { useSyncExternalStore } from "react";

/** 로그인 상태(토큰·사용자)를 localStorage에 보관한다. */
export interface User {
  id: number;
  email: string;
  name: string;
}

const KEY = "npd.auth";
const EVT = "npd-auth";

type Stored = { token: string; user: User };

let cacheRaw: string | null | undefined;
let cacheVal: Stored | null = null;

function read(): Stored | null {
  const raw = localStorage.getItem(KEY);
  if (raw !== cacheRaw) {
    cacheRaw = raw;
    try {
      cacheVal = raw ? (JSON.parse(raw) as Stored) : null;
    } catch {
      cacheVal = null;
    }
  }
  return cacheVal;
}

export function getToken(): string | null {
  return typeof window === "undefined" ? null : read()?.token ?? null;
}

export function saveAuth(token: string, user: User) {
  localStorage.setItem(KEY, JSON.stringify({ token, user }));
  window.dispatchEvent(new Event(EVT));
}

export function clearAuth() {
  localStorage.removeItem(KEY);
  window.dispatchEvent(new Event(EVT));
}

/** 로그인 뒤 돌아갈 곳. 다른 사이트로 보내지 않도록 앱 내부 경로만 허용 */
export function safeNext(n: string | null): string {
  return n && n.startsWith("/") && !n.startsWith("//") && !n.startsWith("/login") && !n.startsWith("/signup") && !n.startsWith("/forgot") ? n : "/gantt";
}

function subscribe(cb: () => void) {
  window.addEventListener(EVT, cb);
  window.addEventListener("storage", cb); // 다른 탭에서 로그아웃
  return () => {
    window.removeEventListener(EVT, cb);
    window.removeEventListener("storage", cb);
  };
}

/** undefined = 아직 확인 전(서버 렌더), null = 로그인 안 됨 */
export function useAuth(): Stored | null | undefined {
  return useSyncExternalStore(subscribe, read, () => undefined);
}
