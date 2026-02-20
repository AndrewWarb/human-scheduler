import type {
  AdapterMeta,
  AppSettings,
  Diagnostics,
  Dispatch,
  LifeArea,
  SchedulerEvent,
  SchedulerState,
  Task,
} from "./types";

const BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "";

async function parseResponse<T>(res: Response): Promise<T> {
  const text = await res.text();
  let data: unknown = null;

  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!res.ok) {
    const msg =
      (data as Record<string, Record<string, string>>)?.error?.message ??
      `HTTP ${res.status}`;
    throw new Error(msg);
  }

  return (data ?? {}) as T;
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  return parseResponse<T>(res);
}

async function apiPost<T>(path: string, body: unknown = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(body),
  });
  return parseResponse<T>(res);
}

export async function fetchHealth(): Promise<Record<string, unknown>> {
  return apiGet("/api/health");
}

export async function fetchMeta(): Promise<AdapterMeta> {
  return apiGet("/api/meta");
}

export async function fetchSettings(): Promise<AppSettings> {
  return apiGet("/api/settings");
}

export async function fetchDiagnostics(): Promise<Diagnostics> {
  return apiGet("/api/diagnostics");
}

export async function fetchSchedulerState(): Promise<SchedulerState> {
  return apiGet("/api/scheduler-state");
}

export async function fetchLifeAreas(): Promise<{ items: LifeArea[] }> {
  return apiGet("/api/life-areas");
}

export async function fetchTasks(params?: {
  life_area_id?: string;
  urgency?: string;
  state?: string;
}): Promise<{ items: Task[] }> {
  const qs = new URLSearchParams();
  if (params?.life_area_id) qs.set("life_area_id", params.life_area_id);
  if (params?.urgency) qs.set("urgency", params.urgency);
  if (params?.state) qs.set("state", params.state);
  const query = qs.toString();
  return apiGet(`/api/tasks${query ? `?${query}` : ""}`);
}

export async function fetchDispatch(): Promise<{ dispatch: Dispatch | null }> {
  return apiGet("/api/dispatch");
}

export async function fetchEvents(
  limit = 200,
): Promise<{ items: SchedulerEvent[] }> {
  return apiGet(`/api/events?limit=${limit}`);
}

export async function createLifeArea(body: {
  name: string;
}): Promise<LifeArea> {
  return apiPost("/api/life-areas", {
    name: body.name,
  });
}

export async function deleteLifeArea(
  lifeAreaId: number,
): Promise<{ life_area: LifeArea; deleted_task_count: number }> {
  return apiPost(`/api/life-areas/${lifeAreaId}/delete`, {});
}

export async function renameLifeArea(
  lifeAreaId: number,
  name: string,
): Promise<LifeArea> {
  return apiPost(`/api/life-areas/${lifeAreaId}/rename`, { name });
}

export async function createTask(body: {
  title: string;
  life_area_id: number;
  urgency_tier: string;
  active_window_start_local?: string | null;
  active_window_end_local?: string | null;
}): Promise<Task> {
  return apiPost("/api/tasks", body);
}

export async function whatNext(): Promise<{ dispatch: Dispatch | null }> {
  return apiPost("/api/what-next", {});
}

export async function resetSimulation(): Promise<{
  status: "ok";
  reset_task_count: number;
}> {
  return apiPost("/api/reset", {});
}

export async function taskAction(
  taskId: number,
  action: "pause" | "resume" | "complete" | "delete",
): Promise<unknown> {
  return apiPost(`/api/tasks/${taskId}/${action}`, {});
}

export async function updateTaskWindow(
  taskId: number,
  body: {
    active_window_start_local?: string | null;
    active_window_end_local?: string | null;
  },
): Promise<Task> {
  return apiPost(`/api/tasks/${taskId}/window`, body);
}

export async function updateTaskUrgency(
  taskId: number,
  body: {
    urgency_tier: string;
  },
): Promise<Task> {
  return apiPost(`/api/tasks/${taskId}/urgency`, body);
}

export async function renameTask(
  taskId: number,
  title: string,
): Promise<Task> {
  return apiPost(`/api/tasks/${taskId}/rename`, { title });
}
