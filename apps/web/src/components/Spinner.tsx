// Small inline loading indicator shared by page/section loading notices and pending-action buttons.
export function Spinner({ label }: { label?: string }) {
  return <span className="spinner" role="status" aria-label={label ?? "Loading"} />;
}
