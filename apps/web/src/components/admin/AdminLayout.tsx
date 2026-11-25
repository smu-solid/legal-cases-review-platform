import { ReactNode } from "react";

// Shared layout primitives for admin pages (dashboard, campaign detail, adjudication). Keeps
// spacing/width/responsiveness consistent across pages instead of each page hand-rolling its own
// grid/spacing rules; see styles.css's `.admin-*` rules for the actual CSS.

export function AdminPage({
  children,
  ariaLabelledBy,
}: {
  children: ReactNode;
  ariaLabelledBy?: string;
}) {
  return (
    <section className="admin-page" aria-labelledby={ariaLabelledBy}>
      {children}
    </section>
  );
}

export function AdminPageHeader({
  eyebrow,
  title,
  titleId,
  subtitle,
  actions,
}: {
  eyebrow: string;
  title: ReactNode;
  titleId?: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="admin-page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2 id={titleId}>{title}</h2>
        {subtitle}
      </div>
      {actions ? <div className="admin-action-bar">{actions}</div> : null}
    </div>
  );
}

export function AdminSectionCard({
  eyebrow,
  title,
  titleId,
  trailing,
  summary,
  id,
  children,
}: {
  eyebrow: string;
  title: ReactNode;
  titleId: string;
  trailing?: ReactNode;
  summary?: ReactNode;
  id?: string;
  children?: ReactNode;
}) {
  return (
    <section className="admin-card" id={id} aria-labelledby={titleId}>
      <div className="pane-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h3 id={titleId}>{title}</h3>
        </div>
        {trailing}
      </div>
      {summary ? <p className="section-summary">{summary}</p> : null}
      {children}
    </section>
  );
}

export function AdminMetricGrid({ children }: { children: ReactNode }) {
  return <div className="admin-metric-grid">{children}</div>;
}

export function AdminFormGrid({ children }: { children: ReactNode }) {
  return <div className="admin-form-grid">{children}</div>;
}

export function AdminActionBar({ children }: { children: ReactNode }) {
  return <div className="admin-action-bar">{children}</div>;
}

export function AdminEmptyState({
  title,
  children,
  quiet = false,
}: {
  title: string;
  children?: ReactNode;
  quiet?: boolean;
}) {
  return (
    <div className={quiet ? "empty-state quiet" : "empty-state"}>
      <h4>{title}</h4>
      {children}
    </div>
  );
}
