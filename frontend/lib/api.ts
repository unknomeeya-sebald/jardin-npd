import { clearAuth, getToken, type User } from "@/lib/auth";

export const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type Signal = "초록" | "노랑" | "빨강" | "회색" | "확인 필요";

export interface Product {
  id: number;
  name: string;
  launch_date: string;
  product_type: string;
  process: string;
}

export interface SchedTask {
  no: number;
  name: string;
  phase: string | null;
  basis: string;
  start_offset: number | null;
  duration: number | null;
  end_offset: number | null;
  milestone_offset: number | null;
  start: string | null;
  end: string | null;
  d_week_start: number | null;
  d_week_end: number | null;
  predecessors: number[];
  buffer_days: number | null;
  status: string;
  note: string | null;
  actual_end: string | null;
  change_date?: string | null;
  state?: string | null;
  estimated?: boolean;
  inferred?: boolean;
  expected_start?: string | null;
  expected_end?: string | null;
  delay?: number | null;
  fixed?: boolean;
  signal: Signal;
  slack: number | null;
  reason: string;
}

export interface Schedule {
  product: Product;
  as_of: string;
  threshold: number;
  tasks: SchedTask[];
  red_count: number;
  summary?: { expected_launch: string; launch_impact_days: number; signal: Signal };
}

export interface Holiday {
  date: string;
  name: string;
  kind: string;
}

export interface OverlapWeek {
  week_start: string;
  entries: { product: string; task_no: number; task_name: string; start: string; end: string }[];
}

export interface AbsorbResult {
  delayed_task: number;
  delay: number;
  limit_task: number;
  absorbed: { task_no: number; task_name: string; slack: number; absorbed: number; slack_source: string }[];
  remaining: number;
  launch: string;
  launch_impact_days: number;
  impacted_launch: string;
  alert: string | null;
  assumption: string;
}

export interface TaskBase {
  no: number;
  name: string;
  phase: string | null;
  start_offset: number | null;
  duration: number | null;
  basis: string;
  predecessors: string | null;
  buffer_days: number | null;
  note: string | null;
  dept?: string | null;
  fixed_end?: number | null;
  input_source?: string | null; // 엑셀 | 앱 | 디자인 시트 | 없음
}

export type Settings = Record<string, { value: string; note: string | null }>;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  const token = getToken();
  const headers: Record<string, string> = init?.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    r = await fetch(`${API}${path}`, {
      ...init,
      headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
      cache: "no-store",
    });
  } catch {
    throw new Error(`백엔드(${API})에 연결할 수 없습니다. 백엔드 서버가 켜져 있는지 확인하세요.`);
  }
  if (!r.ok) {
    // 토큰 만료·무효: 저장된 로그인 정보를 지우면 화면이 로그인 페이지로 이동한다
    if (r.status === 401 && token) clearAuth();
    let msg = `${r.status}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail
        : Array.isArray(j.detail) ? j.detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, "")).join(" / ")
        : JSON.stringify(j.detail);
    } catch {}
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export interface SlackStatus {
  configured: boolean;
  mode: "webhook" | "bot" | null;
  channel: string | null;
  interval_min: number;
}

export type ActionStatus = "할 일" | "진행 중" | "완료";

export interface ActionItem {
  id: number;
  title: string;
  detail: string | null;
  owner: string | null;
  due: string | null;
  product: string | null;
  status: ActionStatus;
  source: "slack" | "text";
  source_text: string | null;
  source_link: string | null;
  created_by: string | null;
  created_at: string | null;
}

export interface ActionSources {
  llm: boolean;
  model: string;
  slack: boolean;
  channel: string;
  last_synced: string | null;
}

type Extracted = { messages: number; created: ActionItem[] };

type AuthRes = { token: string; user: User };

export const api = {
  signup: (b: { email: string; name: string; password: string }) =>
    req<AuthRes>("/api/auth/signup", { method: "POST", body: JSON.stringify(b) }),
  login: (b: { email: string; password: string }) =>
    req<AuthRes>("/api/auth/login", { method: "POST", body: JSON.stringify(b) }),
  forgot: (b: { email: string }) =>
    req<{ sent: boolean; via: string; ttl_min: number }>("/api/auth/forgot", { method: "POST", body: JSON.stringify(b) }),
  resetPassword: (b: { email: string; code: string; password: string }) =>
    req<AuthRes>("/api/auth/reset", { method: "POST", body: JSON.stringify(b) }),
  me: () => req<User>("/api/auth/me"),
  actions: () => req<ActionItem[]>("/api/actions"),
  actionSources: () => req<ActionSources>("/api/actions/sources"),
  extractSlack: (days: number, full = false) =>
    req<Extracted>("/api/actions/extract/slack", { method: "POST", body: JSON.stringify({ days, full }) }),
  extractText: (text: string) => req<Extracted>("/api/actions/extract/text", { method: "POST", body: JSON.stringify({ text }) }),
  patchAction: (id: number, b: Partial<Pick<ActionItem, "title" | "owner" | "due" | "status" | "product">>) =>
    req<ActionItem>(`/api/actions/${id}`, { method: "PATCH", body: JSON.stringify(b) }),
  deleteAction: (id: number) => req(`/api/actions/${id}`, { method: "DELETE" }),
  slackStatus: () => req<SlackStatus>("/api/alerts/slack"),
  slackTest: () => req<{ sent: boolean }>("/api/alerts/slack/test", { method: "POST" }),
  alertsCheck: () => req<{ queued: Record<string, number | string> }>("/api/alerts/check", { method: "POST" }),
  health: () => req<{ db: string; tasks: number; tasks_needing_check: number }>("/api/health"),
  products: () => req<Product[]>("/api/products"),
  createProduct: (b: Omit<Product, "id">) => req<{ id: number }>("/api/products", { method: "POST", body: JSON.stringify(b) }),
  deleteProduct: (id: number) => req(`/api/products/${id}`, { method: "DELETE" }),
  schedule: (id: number, asOf: string) => req<Schedule>(`/api/products/${id}/schedule?as_of=${asOf}`),
  tasks: () => req<TaskBase[]>("/api/tasks"),
  holidays: () => req<Holiday[]>("/api/holidays"),
  settings: () => req<Settings>("/api/settings"),
  putSetting: (k: string, v: string) => req(`/api/settings/${k}`, { method: "PUT", body: JSON.stringify({ value: v }) }),
  putActual: (pid: number, no: number, d: string | null) =>
    req(`/api/products/${pid}/actuals/${no}`, { method: "PUT", body: JSON.stringify({ actual_end: d }) }),
  concurrent: (ids: number[]) => req<OverlapWeek[]>(`/api/concurrent?ids=${ids.join(",")}`),
  absorb: (pid: number, task_no: number, delay_days: number) =>
    req<AbsorbResult>(`/api/products/${pid}/absorb`, { method: "POST", body: JSON.stringify({ task_no, delay_days }) }),
  importTasks: (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    return req<{ imported: number }>("/api/tasks/import", { method: "POST", body: fd });
  },
};
