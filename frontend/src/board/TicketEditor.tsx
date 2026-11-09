/** The form for a new ticket or an existing one, in a native modal <dialog>. */

import { type FormEvent, useEffect, useRef, useState } from "react";

import { PRIORITIES, STATUSES, type Ticket, type TicketFields, type TicketPriority, type TicketStatus } from "../api";

type Props = {
  /** null: a new ticket. */
  ticket: Ticket | null;
  /** Gets every field of the form; the board works out what changed. */
  onSubmit: (fields: TicketFields) => Promise<void>;
  /** Only for an existing ticket. */
  onDelete?: () => Promise<void>;
  onClose: () => void;
};

export function TicketEditor({ ticket, onSubmit, onDelete, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState(ticket?.title ?? "");
  const [description, setDescription] = useState(ticket?.description ?? "");
  const [status, setStatus] = useState<TicketStatus>(ticket?.status ?? "open");
  const [priority, setPriority] = useState<TicketPriority>(ticket?.priority ?? "medium");

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();

    onClose();
    await onSubmit({ title, description, status, priority });
  };

  const remove = async () => {
    onClose();
    await onDelete?.();
  };

  return (
    // onClose: also fires when Escape closes the dialog.
    <dialog ref={dialog} className="editor" onClose={onClose}>
      <form onSubmit={submit}>
        <h2>{ticket ? `Ticket #${ticket.id}` : "New ticket"}</h2>

        <label>
          Title
          <input value={title} onChange={(event) => setTitle(event.target.value)} required maxLength={200} />
        </label>

        <label>
          Description
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} required rows={6} />
        </label>

        <div className="editor-row">
          <label>
            Status
            <select value={status} onChange={(event) => setStatus(event.target.value as TicketStatus)}>
              {STATUSES.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>

          <label>
            Priority
            <select value={priority} onChange={(event) => setPriority(event.target.value as TicketPriority)}>
              {PRIORITIES.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="editor-buttons">
          {onDelete && (
            <button type="button" className="danger" onClick={remove}>
              Delete
            </button>
          )}
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit">{ticket ? "Save" : "Create"}</button>
        </div>
      </form>
    </dialog>
  );
}
