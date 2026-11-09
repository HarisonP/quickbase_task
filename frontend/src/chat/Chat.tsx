/** The chat pane: assistant-ui's primitives (unstyled building blocks) wired to our adapter. */

import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  type TextMessagePartComponent,
  type ThreadMessageLike,
  ThreadPrimitive,
  useLocalRuntime,
} from "@assistant-ui/react";
import { useEffect, useMemo, useState } from "react";

import { listMessages, type Tenant } from "../api";
import { createAdapter } from "./adapter";
import { MutateTicketCall, ToolCall } from "./ToolCall";

type ChatProps = { tenant: Tenant; conversationId: string };

/** Loads the conversation's saved messages, then shows the chat starting from them. */
export function Chat({ tenant, conversationId }: ChatProps) {
  const [history, setHistory] = useState<ThreadMessageLike[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    listMessages(tenant, conversationId)
      .then((messages) => {
        if (cancelled) return;
        setHistory(messages.map((m) => ({ role: m.role, content: m.content, createdAt: new Date(m.created_at) })));
      })
      .catch((reason: unknown) => !cancelled && setError(String(reason)));

    return () => {
      cancelled = true;
    };
  }, [tenant, conversationId]);

  if (error) return <p className="error">Could not load the conversation: {error}</p>;
  if (!history) return <p className="placeholder">Loading…</p>;
  return <ChatThread tenant={tenant} conversationId={conversationId} history={history} />;
}

function ChatThread({ tenant, conversationId, history }: ChatProps & { history: ThreadMessageLike[] }) {
  const adapter = useMemo(() => createAdapter(tenant, conversationId), [tenant, conversationId]);
  // initialMessages is read once: the runtime keeps the chat state from then on.
  const runtime = useLocalRuntime(adapter, { initialMessages: history });

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
