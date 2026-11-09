/**
 * The ticket board: one column per status. Drag a card to another column to change its status;
 * click a card to edit or delete it; "New ticket" creates one. All are the user's own actions on
 * /api/tickets, so there is no approval step.
 */

import {
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { useEffect, useState } from "react";

import {
  createTicket,
  deleteTicket,
  listTickets,
  STATUSES,
  type Tenant,
  type Ticket,
  type TicketChanges,
  type TicketFields,
  type TicketStatus,
  updateTicket,
} from "../api";
import { TicketEditor } from "./TicketEditor";

const COLUMN_TITLES: Record<TicketStatus, string> = { open: "Open", in_progress: "In progress", closed: "Closed" };

/** Which ticket the form is open for: an existing one, a new one, or none (form closed). */
type Editing = Ticket | "new" | null;

/** `version`: bumped by the parent when the agent may have changed tickets, to reload them. */
export function Board({ tenant, version }: { tenant: Tenant; version: number }) {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dragged, setDragged] = useState<Ticket | null>(null);
  const [editing, setEditing] = useState<Editing>(null);

  // A drag only starts after the pointer moves 5px, so a plain click still opens the editor.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  useEffect(() => {
    let cancelled = false;

    // `version` isn't read here: changing it is what triggers the reload.
    void version;
    listTickets(tenant)
      .then((list) => !cancelled && setTickets(list))
      .catch((reason: unknown) => !cancelled && setError(String(reason)));

    return () => {
      cancelled = true;
    };
  }, [tenant, version]);

  /** Shows the change at once, then saves it; puts the old ticket back if saving fails. */
  const save = async (ticket: Ticket, changes: TicketChanges) => {
    setError(null);
    setTickets((list) => list.map((t) => (t.id === ticket.id ? { ...t, ...changes } : t)));

    try {
      const saved = await updateTicket(tenant, ticket.id, changes);
      setTickets((list) => list.map((t) => (t.id === saved.id ? saved : t)));
    } catch (reason) {
      setTickets((list) => list.map((t) => (t.id === ticket.id ? ticket : t)));
      setError(`Could not save ticket #${ticket.id}: ${String(reason)}`);
    }
  };

  /** Not optimistic: the card can only be shown once the server has given the ticket its id. */
  const create = async (fields: TicketFields) => {
    setError(null);

    try {
      const created = await createTicket(tenant, fields);
      setTickets((list) => [...list, created]);
    } catch (reason) {
      setError(`Could not create the ticket: ${String(reason)}`);
    }
  };

  /** Removes the card at once, then deletes; puts it back if deleting fails. */
  const remove = async (ticket: Ticket) => {
    if (!window.confirm(`Delete ticket #${ticket.id}?`)) return;

    setError(null);
    setTickets((list) => list.filter((t) => t.id !== ticket.id));

    try {
      await deleteTicket(tenant, ticket.id);
    } catch (reason) {
      setTickets((list) => [...list, ticket].sort((a, b) => a.id - b.id));
      setError(`Could not delete ticket #${ticket.id}: ${String(reason)}`);
    }
  };

  /** The form was submitted: create the new ticket, or save only the fields that changed. */
  const submit = async (ticket: Ticket | null, fields: TicketFields) => {
    if (!ticket) return create(fields);

    const changes: TicketChanges = {};
    if (fields.title !== ticket.title) changes.title = fields.title;
    if (fields.description !== ticket.description) changes.description = fields.description;
    if (fields.status !== ticket.status) changes.status = fields.status;
    if (fields.priority !== ticket.priority) changes.priority = fields.priority;

    if (Object.keys(changes).length > 0) await save(ticket, changes);
  };

  const onDragStart = (event: DragStartEvent) => {
    setDragged(tickets.find((ticket) => ticket.id === event.active.id) ?? null);
  };

  const onDragEnd = (event: DragEndEvent) => {
    setDragged(null);

    const ticket = tickets.find((t) => t.id === event.active.id);
    const status = event.over?.id as TicketStatus | undefined;
    if (ticket && status && status !== ticket.status) void save(ticket, { status });
  };

  return (
    <div className="board">
      <div className="board-toolbar">
        <button type="button" onClick={() => setEditing("new")}>
          New ticket
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
        <div className="board-columns">
          {STATUSES.map((status) => (
            <Column
              key={status}
              status={status}
              tickets={tickets.filter((ticket) => ticket.status === status)}
              onOpen={setEditing}
            />
          ))}
        </div>

        {/* The card that follows the pointer while dragging (drawn above everything, not clipped by columns). */}
        <DragOverlay>{dragged && <TicketCard ticket={dragged} />}</DragOverlay>
      </DndContext>

      {editing === "new" && (
        <TicketEditor ticket={null} onSubmit={(fields) => submit(null, fields)} onClose={() => setEditing(null)} />
      )}

      {editing && editing !== "new" && (
        <TicketEditor
          ticket={editing}
          onSubmit={(fields) => submit(editing, fields)}
          onDelete={() => remove(editing)}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

type ColumnProps = { status: TicketStatus; tickets: Ticket[]; onOpen: (ticket: Ticket) => void };

function Column({ status, tickets, onOpen }: ColumnProps) {
  // The column's id is its status: dropping a card here gives `over.id === status`.
  const { setNodeRef, isOver } = useDroppable({ id: status });

  return (
    <section ref={setNodeRef} className={isOver ? "column over" : "column"}>
      <h2>
        {COLUMN_TITLES[status]} <span className="count">{tickets.length}</span>
      </h2>

      {tickets.map((ticket) => (
        <DraggableCard key={ticket.id} ticket={ticket} onOpen={onOpen} />
      ))}
    </section>
  );
}

function DraggableCard({ ticket, onOpen }: { ticket: Ticket; onOpen: (ticket: Ticket) => void }) {
  const { setNodeRef, attributes, listeners, isDragging } = useDraggable({ id: ticket.id });

  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      className={isDragging ? "card-slot dragging" : "card-slot"}
      onClick={() => onOpen(ticket)}
      onKeyDown={(event) => event.key === "Enter" && onOpen(ticket)}
    >
      <TicketCard ticket={ticket} />
    </div>
  );
}

function TicketCard({ ticket }: { ticket: Ticket }) {
  return (
    <article className="card">
      <header>
        <span className="card-id">#{ticket.id}</span>
        <span className={`priority ${ticket.priority}`}>{ticket.priority}</span>
      </header>
      <p className="card-title">{ticket.title}</p>
    </article>
  );
}
