// Тонкая обёртка над fetch. credentials:"include" — чтобы уходила cookie-сессия.

export interface Device {
  device_id: string;
  friendly_name: string;
  host: string;
  user: string;
  last_file: string;
  last_seen: string | null;
  online: boolean;
  views: number; // число ракурсов (видеодорожек)
  studio_id: number | null;
  studio: string;   // «Пролетарская (лазер)»
  network: string;  // «НЕЖНО» — пусто у одиночных студий
  tz: string;       // часовой пояс студии: показываем время камеры, а не браузера
}

export interface Studio {
  id: number;
  name: string;
  network: string;
  tz: string;
  devices: string[];
}

export interface PanelUser {
  username: string;
  is_admin: boolean;
  network: string;
  created_at?: string | null;
}

export interface PromptScope {
  scope: "global" | "network" | "studio";
  scope_key: string;
  title: string;
  editable: boolean;
}

export interface PromptItem {
  key: string;
  title: string;
  default: string;
  value: string;      // задано на этом уровне («» = наследуем)
  effective: string;  // что реально уходит в модель
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* тело не JSON */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface TimeRange {
  start: number; // epoch ms (UTC)
  end: number;
}

export interface EventRange extends TimeRange {
  kind: string; // тип спец-записи, напр. "zoom"
}

export interface Distraction extends TimeRange {
  label: string; // что было на экране (зрение по кадрам), напр. "YouTube"
}

export interface TranscriptLine {
  id: number;
  start: number; // epoch ms (UTC)
  end: number;
  text: string;
}

export interface TranscribeStatus {
  enabled: boolean;
  model: string;
  attempts: number;
  ok: number;
  failed: number;
  retries: number;
  last_ok_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
}

export interface Highlight {
  t: number; // epoch ms (UTC)
  text: string;
  kind: string; // objection|upsell|contra|promise|complaint|redflag|other
}

export interface Participant {
  role: string; // master|seller|client|other
  note: string;
}

export interface CleanTurn {
  speaker: string;
  t: number;
  text: string;
}

export type EpisodeType = "consultation" | "sale" | "distraction" | "internal" | "other";

export interface ScreenSample {
  t: number; // epoch ms (UTC)
  activity: string; // work|communication|entertainment|idle|unknown
  label: string; // что на экране: "CRM/расписание", "YouTube", "Telegram"…
  distraction: boolean;
  note: string;
}

export interface Conversation {
  id: number;
  start: number; // epoch ms (UTC)
  end: number;
  type: EpisodeType;
  title: string;
  score: number | null;
  summary: string;
  participants: Participant[];
  criteria: Record<string, number>;
  seller_score: number | null;
  sentiment: string | null; // happy|neutral|hesitant|unhappy
  screen: string; // преобладающая метка экрана эпизода (зрение Pixtral)
  screens: ScreenSample[];
  flags: string[];
  highlights: Highlight[];
  clean: CleanTurn[];
}

export interface Objection {
  device_id: string;
  device_name: string;
  t: number; // epoch ms
  text: string;
  kind: string; // objection|contra|complaint|redflag
  conv_type: string;
  score: number | null;
}

export function liveUrl(deviceId: string, view = 0): string {
  return `/api/devices/${encodeURIComponent(deviceId)}/live.m3u8?view=${view}`;
}

export function frameUrl(deviceId: string, ms: number): string {
  return `/api/devices/${encodeURIComponent(deviceId)}/frame?ts=${Math.round(ms)}`;
}

export function archiveUrl(deviceId: string, fromISO: string, toISO: string, view = 0): string {
  const id = encodeURIComponent(deviceId);
  return `/api/devices/${id}/archive.m3u8?from=${encodeURIComponent(fromISO)}&to=${encodeURIComponent(toISO)}&view=${view}`;
}

export function exportUrl(deviceId: string, fromISO: string, toISO: string, view = 0): string {
  const id = encodeURIComponent(deviceId);
  return `/api/devices/${id}/export?from=${encodeURIComponent(fromISO)}&to=${encodeURIComponent(toISO)}&view=${view}`;
}

export function thumbUrl(deviceId: string, bust?: string | null): string {
  const base = `/hls/${encodeURIComponent(deviceId)}/thumb.jpg`;
  return bust ? `${base}?t=${encodeURIComponent(bust)}` : base;
}

export const api = {
  me: () => request<{ username: string; is_admin: boolean }>("/auth/me"),
  login: (username: string, password: string) =>
    request<{ username: string; is_admin: boolean }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<{ status: string }>("/auth/logout", { method: "POST" }),
  devices: () => request<Device[]>("/devices"),
  // ── Администрирование ────────────────────────────────────────────────
  studios: () => request<Studio[]>("/admin/studios"),
  createStudio: (body: { name: string; network: string; tz: string }) =>
    request<Studio>("/admin/studios", { method: "POST", body: JSON.stringify(body) }),
  updateStudio: (id: number, body: { name: string; network: string; tz: string }) =>
    request<Studio>(`/admin/studios/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteStudio: (id: number) =>
    request<{ status: string }>(`/admin/studios/${id}`, { method: "DELETE" }),
  assignDevice: (deviceId: string, studioId: number | null) =>
    request<{ status: string }>(
      `/admin/devices/${encodeURIComponent(deviceId)}/studio` +
        (studioId === null ? "" : `?studio_id=${studioId}`),
      { method: "PATCH" },
    ),
  users: () => request<PanelUser[]>("/admin/users"),
  createUser: (body: { username: string; password: string; is_admin: boolean; network: string }) =>
    request<PanelUser>("/admin/users", { method: "POST", body: JSON.stringify(body) }),
  setUserNetwork: (username: string, network: string) =>
    request<PanelUser>(`/admin/users/${encodeURIComponent(username)}/network`, {
      method: "PUT",
      body: JSON.stringify({ network }),
    }),
  networks: () => request<string[]>("/admin/networks"),
  deleteUser: (username: string) =>
    request<{ status: string }>(`/admin/users/${encodeURIComponent(username)}`, {
      method: "DELETE",
    }),

  // ── Промпты ИИ ───────────────────────────────────────────────────────
  prompts: (scope: string, scopeKey: string) =>
    request<{
      scope: string;
      scope_key: string;
      editable: boolean;
      scopes: PromptScope[];
      items: PromptItem[];
    }>(`/prompts?scope=${encodeURIComponent(scope)}&scope_key=${encodeURIComponent(scopeKey)}`),
  savePrompt: (body: { scope: string; scope_key: string; key: string; text: string }) =>
    request<{ status: string }>("/prompts", { method: "PUT", body: JSON.stringify(body) }),

  renameDevice: (deviceId: string, friendlyName: string) =>
    request<Device>(`/devices/${encodeURIComponent(deviceId)}`, {
      method: "PATCH",
      body: JSON.stringify({ friendly_name: friendlyName }),
    }),
  timeline: (deviceId: string, fromISO: string, toISO: string) =>
    request<{
      ranges: TimeRange[];
      events: EventRange[];
      idle: TimeRange[];
      distractions: Distraction[];
      segments: number;
    }>(
      `/devices/${encodeURIComponent(deviceId)}/timeline?from=${encodeURIComponent(
        fromISO,
      )}&to=${encodeURIComponent(toISO)}`,
    ),
  transcript: (deviceId: string, fromISO: string, toISO: string, q?: string) =>
    request<TranscriptLine[]>(
      `/devices/${encodeURIComponent(deviceId)}/transcript?from=${encodeURIComponent(
        fromISO,
      )}&to=${encodeURIComponent(toISO)}${q ? `&q=${encodeURIComponent(q)}` : ""}`,
    ),
  transcribeStatus: () => request<TranscribeStatus>("/transcribe/status"),
  conversations: (deviceId: string, fromISO: string, toISO: string) =>
    request<Conversation[]>(
      `/devices/${encodeURIComponent(deviceId)}/conversations?from=${encodeURIComponent(
        fromISO,
      )}&to=${encodeURIComponent(toISO)}`,
    ),
  analyzeStatus: () => request<TranscribeStatus>("/analyze/status"),
  visionStatus: () => request<TranscribeStatus>("/vision/status"),
  search: (query: string, limit?: number) =>
    request<{ results: SearchResult[] }>(
      `/search?q=${encodeURIComponent(query)}${limit ? `&limit=${limit}` : ""}`,
    ),
  objections: (limit?: number) =>
    request<{ items: Objection[] }>(`/objections${limit ? `?limit=${limit}` : ""}`),
};

export interface SearchResult {
  id: number;
  device_id: string;
  device_name: string;
  start: number; // epoch ms
  end: number;
  type: EpisodeType;
  title: string;
  score: number | null;
  summary: string;
  similarity: number;
}
