/** Calls to our FastAPI backend. Every request names the tenant in X-Tenant-ID (our stand-in for auth). */

import { EventSourceParserStream } from "eventsource-parser/stream";

export const TENANTS = ["acme", "globex", "initech"] as const;
export type Tenant = (typeof TENANTS)[number];

export type Decision = "approve" | "reject";

/** One event of a chat stream, as sent by the backend's `stream_run`. */
export type ChatEvent =
  | { event: "token"; data: { content: string } }
  | { event: "tool_call"; data: { id: string; tool: string; args: Record<string, unknown> } }
  | { event: "tool_result"; data: { id: string; tool: string; content: string; status: "success" | "error" } }
  | { event: "approval_required"; data: { conversation_id: string; actions: { tool: string; args: unknown }[] } }
  | { event: "done"; data: Record<string, never> }
  | { event: "error"; data: { message: string } };

function headers(tenant: Tenant): HeadersInit {
  return { "Content-Type": "application/json", "X-Tenant-ID": tenant };
}

async function post(tenant: Tenant, path: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  const response = await fetch(path, { method: "POST", headers: headers(tenant), body: JSON.stringify(body), signal });

  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response;
}

/** The SSE events of a streaming response, parsed (POST + fetch, since EventSource can't send a body or headers). */
async function* readEvents(response: Response): AsyncGenerator<ChatEvent> {
  if (!response.body) throw new Error("Response has no body");

  const messages = response.body.pipeThrough(new TextDecoderStream()).pipeThrough(new EventSourceParserStream());

  for await (const message of messages) {
    yield { event: message.event, data: JSON.parse(message.data) } as ChatEvent;
  }
}

export async function createConversation(tenant: Tenant): Promise<string> {
  const response = await post(tenant, "/api/conversations", {});

  const conversation: { id: string } = await response.json();
  return conversation.id;
}

/** Sends a message and streams the agent's answer. */
export async function* streamChat(
  tenant: Tenant,
  conversationId: string,
  message: string,
  signal: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const response = await post(tenant, `/api/conversations/${conversationId}/chat`, { message }, signal);
  yield* readEvents(response);
}

/** Answers the pending approvals (one decision per action, in order) and streams the rest of the run. */
export async function* streamResume(
  tenant: Tenant,
  conversationId: string,
  decisions: Decision[],
  signal: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const response = await post(tenant, `/api/conversations/${conversationId}/resume`, { decisions }, signal);
  yield* readEvents(response);
}
