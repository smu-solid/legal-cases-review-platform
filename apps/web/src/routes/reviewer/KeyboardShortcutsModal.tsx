const SHORTCUTS: { keys: string; action: string }[] = [
  { keys: "j / k / ↓ / ↑", action: "Next / previous field or Add row" },
  { keys: "g", action: "Jump to next group" },
  { keys: "1 / 2", action: "Extracted value correct: Yes / No" },
  { keys: "3 / 4", action: "Extracted provenance correct: Yes / No" },
  { keys: "m", action: "Mark supporting provenance in Text view" },
  { keys: "s / Cmd+S / Ctrl+S", action: "Save draft" },
  {
    keys: "Enter",
    action: "Open focused Add row; activate focused button; otherwise submit a ready field",
  },
  { keys: "Cmd/Ctrl+A", action: "Select all text" },
  { keys: "?", action: "Open / close this help" },
  { keys: "Esc", action: "Close dialog / cancel provenance picking" },
];

export function KeyboardShortcutsModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h3 id="shortcuts-title">Keyboard shortcuts</h3>
        <table className="shortcuts-table">
          <tbody>
            {SHORTCUTS.map((row) => (
              <tr key={row.keys}>
                <td>
                  <kbd>{row.keys}</kbd>
                </td>
                <td>{row.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
