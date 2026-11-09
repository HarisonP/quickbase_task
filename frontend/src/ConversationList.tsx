/** The sidebar: the tenant's conversations (newest first), a button to start one, and delete buttons. */

import type { Conversation } from "./api";

type Props = {
  conversations: Conversation[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
};

export function ConversationList({ conversations, selectedId, onSelect, onNew, onDelete }: Props) {
  return (
    <nav className="pane conversations">
      <button type="button" className="new-conversation" onClick={onNew}>
        + New chat
      </button>

      <ul>
        {conversations.map((conversation) => (
          <li
            key={conversation.id}
            className={conversation.id === selectedId ? "conversation selected" : "conversation"}
          >
            <button type="button" className="conversation-open" onClick={() => onSelect(conversation.id)}>
              {new Date(conversation.created_at).toLocaleString()}
            </button>
            <button
              type="button"
              className="conversation-delete"
              title="Delete chat"
              onClick={() => onDelete(conversation.id)}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
