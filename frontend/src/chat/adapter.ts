/**
 * The bridge between assistant-ui and our backend.
 *
 * assistant-ui's LocalRuntime owns the chat state and calls `run` whenever the assistant should
 * answer. `run` streams our SSE events and yields the assistant message's content so far, which
 * assistant-ui renders: text parts, and tool-call parts (the trace).
 *
 * Approval: on `approval_required` we mark the pending tool calls with `approval` and end the run
 * as "requires-action". assistant-ui then waits; the approval modal records the user's decision
 * (respondToApproval), and assistant-ui calls `run` again on the same message. That second call
 * sends the decisions to /resume and streams the rest of the run.
 */

import type {
  ChatModelAdapter,
  ThreadAssistantMessagePart,
  ThreadMessage,
  ToolCallMessagePart,
} from "@assistant-ui/react";

import { type ChatEvent, type Decision, streamChat, streamResume, type Tenant } from "../api";

const REQUIRES_APPROVAL = { type: "requires-action", reason: "tool-calls" } as const;

export function createAdapter(tenant: Tenant, conversationId: string): ChatModelAdapter {
  // Approvals whose decision was already sent to /resume (a message can pause more than once).
  const answered = new Set<string>();

  return {
    async *run({ messages, abortSignal, unstable_getMessage }) {
      const current = unstable_getMessage();
      const decisions = newDecisions(current, answered);

      const events =
        decisions.length > 0
          ? streamResume(tenant, conversationId, decisions, abortSignal)
          : streamChat(tenant, conversationId, lastUserText(messages), abortSignal);

      const content = new ContentBuilder(current);
      for await (const event of events) {
        const paused = content.apply(event);
        yield paused ? { content: content.parts, status: REQUIRES_APPROVAL } : { content: content.parts };
      }
    },
  };
}

function lastUserText(messages: readonly ThreadMessage[]): string {
  const last = messages.findLast((message) => message.role === "user");

  return (last?.content ?? []).map((part) => (part.type === "text" ? part.text : "")).join("");
}

/** Decisions the user made in the approval modal that the backend hasn't received yet, in order. */
function newDecisions(message: ThreadMessage, answered: Set<string>): Decision[] {
  const decisions: Decision[] = [];

  for (const part of message.content) {
    if (part.type !== "tool-call" || part.approval?.approved === undefined) continue;
    if (answered.has(part.approval.id)) continue;

    answered.add(part.approval.id);
    decisions.push(part.approval.approved ? "approve" : "reject");
  }
  return decisions;
}

/**
 * Turns our stream's events into assistant-ui message parts, in the order they arrive.
 *
 * On a resumed run assistant-ui appends what we yield to the parts the message already has, so
 * tool calls it already shows are skipped. A result for one of them (the approved call that now
 * ran) is yielded under the same id: assistant-ui fills it into the existing part.
 */
class ContentBuilder {
  parts: ThreadAssistantMessagePart[] = [];

  private readonly existing: Map<string, ToolCallMessagePart>;

  constructor(message: ThreadMessage) {
    this.existing = new Map();
    for (const part of message.content) {
      if (part.type === "tool-call") this.existing.set(part.toolCallId, part);
    }
  }

  /** Applies one event; returns true when the run paused for approval. */
  apply(event: ChatEvent): boolean {
    switch (event.event) {
      case "token":
        this.addText(event.data.content);
        return false;

      case "tool_call":
        this.addToolCall(event.data.id, event.data.tool, event.data.args);
        return false;

      case "tool_result":
        this.addToolResult(event.data.id, event.data.content, event.data.status === "error");
        return false;

      case "approval_required":
        this.requestApprovals(event.data.actions.map((action) => action.tool));
        return true;

      case "error":
        this.addText(`\n\n⚠ ${event.data.message}`);
        return false;

      case "done":
        return false;
    }
  }

  private addText(text: string) {
    const last = this.parts.at(-1);

    if (last?.type === "text") {
      this.parts = [...this.parts.slice(0, -1), { type: "text", text: last.text + text }];
    } else {
      this.parts = [...this.parts, { type: "text", text }];
    }
  }

  private addToolCall(id: string, toolName: string, args: Record<string, unknown>) {
    // The approval middleware re-emits the model's message, so the same call can arrive twice.
    if (this.existing.has(id) || this.findToolCall(id) !== -1) return;

    const part: ToolCallMessagePart = {
      type: "tool-call",
      toolCallId: id,
      toolName,
      args: args as ToolCallMessagePart["args"],
      argsText: JSON.stringify(args),
    };
    this.parts = [...this.parts, part];
  }

  private addToolResult(id: string, result: string, isError: boolean) {
    const index = this.findToolCall(id);
    if (index !== -1) {
      this.parts = this.parts.map((part, i) => (i === index ? { ...part, result, isError } : part));
      return;
    }

    // A call from before the pause: yield it with its result so assistant-ui fills it in. A call
    // that already has a result (rejected in the modal) is left as it is.
    const earlier = this.existing.get(id);
    if (earlier && earlier.result === undefined) {
      this.parts = [...this.parts, { ...earlier, result, isError }];
    }
  }

  /** Marks the calls waiting for approval: the first unanswered call of each action's tool, in order. */
  private requestApprovals(toolNames: string[]) {
    for (const toolName of toolNames) {
      const index = this.parts.findIndex(
        (part) =>
          part.type === "tool-call" &&
          part.toolName === toolName &&
          part.result === undefined &&
          part.approval === undefined,
      );
      if (index === -1) continue;

      const part = this.parts[index] as ToolCallMessagePart;
      this.parts = this.parts.map((p, i) => (i === index ? { ...part, approval: { id: part.toolCallId } } : p));
    }
  }

  private findToolCall(id: string): number {
    return this.parts.findIndex((part) => part.type === "tool-call" && part.toolCallId === id);
  }
}
