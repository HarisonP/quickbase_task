/** How tool calls show up in the chat: one trace row per call, and the approval modal for mutate_ticket. */

import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { useEffect, useRef, useState } from "react";

/** The trace row: tool name, arguments and (click to expand) the result. */
export const ToolCall: ToolCallMessagePartComponent = ({ toolName, args, result, isError, approval }) => {
  const label = statusLabel(result, isError, approval?.approved);

  return (
    <details className="tool-call">
      <summary>
        <span className={`tool-status ${label.className}`}>{label.text}</span>
        <code>{toolName}</code>
        <code className="tool-args">{JSON.stringify(args)}</code>
      </summary>
      {result !== undefined && <pre className="tool-result">{formatResult(result)}</pre>}
    </details>
  );
};

/** mutate_ticket: the trace row, plus the approval modal while the call waits for a decision. */
export const MutateTicketCall: ToolCallMessagePartComponent = (props) => {
  const { approval, respondToApproval } = props;
  const waiting = approval !== undefined && approval.approved === undefined && approval.resolution === undefined;

  return (
    <>
      <ToolCall {...props} />
      {waiting && <ApprovalModal args={props.args} onDecide={(approved) => respondToApproval({ approved })} />}
    </>
  );
};

type MutateArgs = { ticket_id?: number; action?: "update" | "delete"; fields?: Record<string, unknown> | null };

/**
 * A native <dialog> opened with showModal(): the rest of the page can't be clicked until the user
 * decides, and Escape is disabled, so the only way out is Approve or Reject.
 */
function ApprovalModal({ args, onDecide }: { args: MutateArgs; onDecide: (approved: boolean) => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  const decide = async (approved: boolean) => {
    setSending(true);

    try {
      await onDecide(approved);
    } finally {
      setSending(false);
    }
  };

  const fields = Object.entries(args.fields ?? {});

  return (
    <dialog ref={dialog} className="approval" onCancel={(event) => event.preventDefault()}>
      <h2>Approve this change?</h2>
      <p>
        The assistant wants to <strong>{args.action}</strong> ticket <strong>#{args.ticket_id}</strong>.
      </p>

      {fields.length > 0 && (
        <table>
          <tbody>
            {fields.map(([name, value]) => (
              <tr key={name}>
                <th>{name}</th>
                <td>{String(value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="approval-buttons">
        <button type="button" className="reject" disabled={sending} onClick={() => decide(false)}>
          Reject
        </button>
        <button type="button" className="approve" disabled={sending} onClick={() => decide(true)}>
          Approve
        </button>
      </div>
    </dialog>
  );
}

function statusLabel(result: unknown, isError: boolean | undefined, approved: boolean | undefined) {
  if (approved === false) return { text: "rejected", className: "error" };
  if (result === undefined) return { text: approved ? "running" : "waiting", className: "pending" };
  if (isError) return { text: "error", className: "error" };
  return { text: "done", className: "ok" };
}

function formatResult(result: unknown): string {
  return typeof result === "string" ? result : JSON.stringify(result, null, 2);
}
