/**
 * The ticket board: one column per status. Drag a card to another column to change its status;
 * click a card to edit it. Both are the user's own edits (PATCH /api/tickets/{id}), no approval.
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
  listTickets,
  STATUSES,
  type Tenant,
  type Ticket,
  type TicketChanges,
  type TicketStatus,
  updateTicket,
} from "../api";
import { TicketEditor } from "./TicketEditor";

const COLUMN_TITLES: Record<TicketStatus, string> = { open: "Open", in_progress: "In progress", closed: "Closed" };

/** `version`: bumped by the parent when the agent may have changed tickets, to reload them. */
export function Board({ tenant, version }: { tenant: Tenant; version: number }) {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dragged, setDragged] = useState<Ticket | null>(null);
  const [editing, setEditing] = useState<Ticket | null>(null);

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

      {editing && (
        <TicketEditor
          ticket={editing}
          onSave={(changes) => save(editing, changes)}
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
