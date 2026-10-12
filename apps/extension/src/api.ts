import { API_BASE } from "./config";
import type { ApiOp, ApiReply } from "./messages";
import { idToken, load } from "./session";

/**
 * The worker's API client: every call carries the reader's ID token (never seen by the page or
 * the content script). A 401 retries once with a refreshed token. Demo readers' calls carry
 * their persona, as in the web app.
 */

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const send = async (force: boolean) => {
    const token = await idToken(force);
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(API_BASE + path, { ...init, headers });
  };
  const res = await send(false);
  return res.status === 401 ? send(true) : res;
}

export async function call<T>(method: string, path: string, body?: unknown): Promise<ApiReply<T>> {
  let res: Response;
  try {
    res = await request(path, {
      method,
      ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
    });
  } catch {
    return { ok: false, status: 0, error: "offline", message: "Gloss couldn't reach its server. Try again." };
  }
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null;
  if (res.ok) return { ok: true, status: res.status, data: data as T };
  const detail = typeof data?.detail === "string" ? data.detail : null;
  return {
    ok: false,
    status: res.status,
    error: String(data?.error ?? detail ?? "error"),
    message: String(data?.message ?? "Something went wrong. Try again."),
  };
}

const enc = encodeURIComponent;

/** One content-script step (DESIGN §8 routes, the same ones the web app uses). */
export async function run(op: ApiOp): Promise<ApiReply> {
  const session = await load();
  const persona = session?.persona ?? null;
  const density = session?.density ?? "balanced";
  const p = persona ? `persona=${encodeURIComponent(persona)}` : "";
  const q = (extra = "") => {
    const parts = [extra, p].filter(Boolean).join("&");
    return parts ? `?${parts}` : "";
  };
  switch (op.op) {
    case "submit":
      return call("POST", "/v1/content", {
        url: op.url, title: op.title, paragraphs: op.paragraphs, defer: true,
      });  // prettier-ignore
    case "analyse":
      return call("POST", `/v1/content/${enc(op.id)}/analyse`, {});
    case "detail":
      return call("GET", `/v1/content/${enc(op.id)}`);
    case "annotations":
      return call("GET", `/v1/content/${enc(op.id)}/annotations${q(`density=${density}${op.refresh ? "&refresh=1" : ""}`)}`);
    case "explain":
      return call("POST", `/v1/explain${q()}`, { content_id: op.id, ...op.target });
    case "events":
      return call("POST", "/v1/events", { persona, events: op.events });
    case "answer":
      return call("PATCH", `/v1/me/graph/${enc(op.concept_id)}${q()}`, { state: op.known ? "known" : "unknown" });
    case "report":
      return call("POST", `/v1/explain/${enc(op.explanation_id)}/report${q()}`, {
        event_id: crypto.randomUUID(), content_id: op.content_id, concept_id: op.concept_id,
      });  // prettier-ignore
  }
}
