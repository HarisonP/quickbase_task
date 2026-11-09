/** The edit form for one ticket, in a native modal <dialog>. Saves only the fields that changed. */

import { type FormEvent, useEffect, useRef, useState } from "react";

import { PRIORITIES, STATUSES, type Ticket, type TicketChanges, type TicketPriority, type TicketStatus } from "../api";

type Props = {
  ticket: Ticket;
  onSave: (changes: TicketChanges) => Promise<void>;
  onClose: () => void;
};

export function TicketEditor({ ticket, onSave, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState(ticket.title);
  const [description, setDescription] = useState(ticket.description);
  const [status, setStatus] = useState<TicketStatus>(ticket.status);
  const [priority, setPriority] = useState<TicketPriority>(ticket.priority);

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();

    const changes: TicketChanges = {};
    if (title !== ticket.title) changes.title = title;
    if (description !== ticket.description) changes.description = description;
    if (status !== ticket.status) changes.status = status;
    if (priority !== ticket.priority) changes.priority = priority;

    onClose();
    if (Object.keys(changes).length > 0) await onSave(changes);
  };

  return (
    // onClose: also fires when Escape closes the dialog.
    <dialog ref={dialog} className="editor" onClose={onClose}>
      <form onSubmit={submit}>
        <h2>Ticket #{ticket.id}</h2>

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
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit">Save</button>
        </div>
      </form>
    </dialog>
  );
}
