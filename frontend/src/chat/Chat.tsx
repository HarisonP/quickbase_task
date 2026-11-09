/** The chat pane: assistant-ui's primitives (unstyled building blocks) wired to our adapter. */

import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  type TextMessagePartComponent,
  ThreadPrimitive,
  useLocalRuntime,
} from "@assistant-ui/react";
import { useMemo } from "react";

import type { Tenant } from "../api";
import { createAdapter } from "./adapter";
import { MutateTicketCall, ToolCall } from "./ToolCall";

export function Chat({ tenant, conversationId }: { tenant: Tenant; conversationId: string }) {
  const adapter = useMemo(() => createAdapter(tenant, conversationId), [tenant, conversationId]);
  const runtime = useLocalRuntime(adapter);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="thread">
        <ThreadPrimitive.Viewport className="thread-viewport">
          <ThreadPrimitive.Empty>
            <p className="thread-empty">Ask about your tickets, e.g. "What are my open tickets?"</p>
          </ThreadPrimitive.Empty>

          <ThreadPrimitive.Messages>
            {({ message }) => (message.role === "user" ? <UserMessage /> : <AssistantMessage />)}
          </ThreadPrimitive.Messages>
        </ThreadPrimitive.Viewport>

        <ComposerPrimitive.Root className="composer">
          <ComposerPrimitive.Input className="composer-input" placeholder="Message the assistant…" />
          <ComposerPrimitive.Send className="composer-send">Send</ComposerPrimitive.Send>
        </ComposerPrimitive.Root>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}

const Text: TextMessagePartComponent = ({ text }) => <p className="message-text">{text}</p>;

function UserMessage() {
  return (
    <MessagePrimitive.Root className="message user">
      <MessagePrimitive.Parts components={{ Text }} />
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="message assistant">
      <MessagePrimitive.Parts
        components={{ Text, tools: { by_name: { mutate_ticket: MutateTicketCall }, Fallback: ToolCall } }}
      />
    </MessagePrimitive.Root>
  );
}
