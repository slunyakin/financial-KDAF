export interface EnrichmentTask {
  task_id: string;
  question_text: string;
  confidence_score: number | null;
  source: string;
  status: "open" | "resolved";
  submitted_by: string | null;
  created_at: string | null;
}

export interface EnrichmentTasksResponse {
  api_version: string;
  items: EnrichmentTask[];
  total: number;
}

export interface GraphWriteRequest {
  cypher: string;
  params?: Record<string, unknown>;
}

export interface GraphWriteResponse {
  api_version: string;
  element_id: string;
}

export function getToken(): string {
  return typeof window !== "undefined" ? localStorage.getItem("kdaf_token") ?? "" : "";
}

const BASE = "/api/v1";

export async function fetchTasks(status: "open" | "resolved" | "all" = "open"): Promise<EnrichmentTasksResponse> {
  const res = await fetch(`${BASE}/enrichment/tasks?status=${status}&limit=100`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!res.ok) throw new Error(`fetchTasks: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function getTask(taskId: string): Promise<EnrichmentTask> {
  const res = await fetch(`${BASE}/enrichment/tasks/${encodeURIComponent(taskId)}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!res.ok) throw new Error(`getTask: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function resolveTask(taskId: string): Promise<EnrichmentTask> {
  const res = await fetch(`${BASE}/enrichment/tasks/${encodeURIComponent(taskId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
    body: JSON.stringify({ status: "resolved" }),
  });
  if (!res.ok) throw new Error(`resolveTask: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function graphWrite(req: GraphWriteRequest): Promise<GraphWriteResponse> {
  const res = await fetch(`${BASE}/graph/write`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`graphWrite: ${res.status} ${await res.text()}`);
  return res.json();
}
