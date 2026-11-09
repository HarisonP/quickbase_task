/** One screen: the ticket board on the left (next step), the chat on the right. */

import { useEffect, useState } from "react";

import { createConversation, type Tenant, TENANTS } from "./api";
import { Chat } from "./chat/Chat";

export function App() {
  const [tenant, setTenant] = useState<Tenant>("acme");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // A new conversation for every tenant switch: conversations belong to one tenant.
  useEffect(() => {
    let cancelled = false;
    setConversationId(null);
    setError(null);

    createConversation(tenant)
      .then((id) => !cancelled && setConversationId(id))
      .catch((reason: unknown) => !cancelled && setError(String(reason)));

    return () => {
      cancelled = true;
    };
  }, [tenant]);

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
        <section className="pane board-pane">
          <p className="placeholder">Ticket board: coming next.</p>
        </section>

        <section className="pane chat-pane">
          {error && <p className="error">Could not start a conversation: {error}</p>}
          {/* key: a new conversation gets a fresh chat state */}
          {conversationId && <Chat key={conversationId} tenant={tenant} conversationId={conversationId} />}
        </section>
      </main>
    </div>
  );
}
