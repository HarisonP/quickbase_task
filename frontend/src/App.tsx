/** One screen: conversations on the side, the ticket board, and the chat. */

import { useCallback, useEffect, useState } from "react";

import {
  type Conversation,
  createConversation,
  deleteConversation,
  listConversations,
  TENANTS,
  type Tenant,
} from "./api";
import { Board } from "./board/Board";
import { ConversationList } from "./ConversationList";
import { Chat } from "./chat/Chat";

export function App() {
  const [tenant, setTenant] = useState<Tenant>("acme");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped when the agent changed a ticket: the board reloads. Stable callback, so the chat's
  // adapter isn't recreated on every render.
  const [boardVersion, setBoardVersion] = useState(0);
  const ticketsChanged = useCallback(() => setBoardVersion((version) => version + 1), []);

  // On a tenant switch: load its conversations and open the newest (or a new one if it has none).
  useEffect(() => {
    let cancelled = false;
    setConversations([]);
    setSelectedId(null);
    setError(null);

    const load = async () => {
      let list = await listConversations(tenant);
      if (list.length === 0) list = [await createConversation(tenant)];

      if (cancelled) return;
      setConversations(list);
      setSelectedId(list[0].id);
    };
    load().catch((reason: unknown) => !cancelled && setError(String(reason)));

    return () => {
      cancelled = true;
    };
  }, [tenant]);

  const startConversation = async () => {
    try {
      const conversation = await createConversation(tenant);

      setConversations((list) => [conversation, ...list]);
      setSelectedId(conversation.id);
    } catch (reason) {
      setError(String(reason));
    }
  };

  const removeConversation = async (id: string) => {
    if (!window.confirm("Delete this chat?")) return;

    try {
      await deleteConversation(tenant, id);
    } catch (reason) {
      setError(String(reason));
      return;
    }

    const remaining = conversations.filter((conversation) => conversation.id !== id);
    setConversations(remaining);

    // Deleted the open chat: open the next one, or start a new chat if none is left.
    if (id !== selectedId) return;
    if (remaining.length > 0) setSelectedId(remaining[0].id);
    else await startConversation();
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Ticket Assistant</h1>
        <label>
          Tenant{" "}
          <select value={tenant} onChange={(event) => setTenant(event.target.value as Tenant)}>
            {TENANTS.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </label>
      </header>

      <main className="app-panes">
        <ConversationList
          conversations={conversations}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onNew={startConversation}
          onDelete={removeConversation}
        />

        <section className="pane board-pane">
          <Board tenant={tenant} version={boardVersion} />
        </section>

        <section className="pane chat-pane">
          {error && <p className="error">{error}</p>}
          {/* key: switching conversation remounts the chat with that conversation's history */}
          {selectedId && (
            <Chat key={selectedId} tenant={tenant} conversationId={selectedId} onTicketsChanged={ticketsChanged} />
          )}
        </section>
      </main>
    </div>
  );
}
