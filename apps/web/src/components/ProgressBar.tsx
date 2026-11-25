// Shared progress bar: a filled track plus a "value/total (percent%)" caption. Used by the
// reviewer's campaign/case progress cards and the admin campaign monitor grid so both surfaces
// render case-level progress the same way.
export function ProgressBar({
  value,
  total,
  label,
}: {
  value: number;
  total: number;
  label: string;
}) {
  const percent = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div className="progress-bar">
      <div className="progress-bar-track" role="img" aria-label={`${label}: ${percent}% complete`}>
        <span className="progress-bar-fill" style={{ width: `${percent}%` }} />
      </div>
      <p className="progress-bar-caption">
        {value}/{total} · {percent}%
      </p>
    </div>
  );
}
