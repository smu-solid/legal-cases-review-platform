import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { ProgressBar } from "./ProgressBar";

export function WorkspaceCaseHeader({
  backHref,
  backLabel,
  campaignProgress,
  eyebrow,
  title,
  titleId,
  actions,
}: {
  backHref: string;
  backLabel: string;
  campaignProgress: { completed: number; total: number } | null;
  eyebrow: string;
  title: string;
  titleId: string;
  actions: ReactNode;
}) {
  const pct = campaignProgress?.total
    ? Math.round((campaignProgress.completed / campaignProgress.total) * 100)
    : 0;
  return (
    <div className="workspace-header compact-header">
      <div className="workspace-header-left">
        <Link className="breadcrumb-back breadcrumb-back-onblue" to={backHref}>
          ← {backLabel}
        </Link>
        {campaignProgress ? (
          <div className="workspace-campaign-progress" aria-label="Your campaign progress">
            <p className="eyebrow">Your campaign</p>
            <ProgressBar
              value={campaignProgress.completed}
              total={campaignProgress.total}
              label="Campaign case progress"
            />
            <span className="workspace-progress-caption">
              {campaignProgress.completed}/{campaignProgress.total} cases · {pct}%
            </span>
          </div>
        ) : (
          <div className="workspace-header-left-spacer" aria-hidden="true" />
        )}
      </div>
      <div className="workspace-header-center">
        <p className="eyebrow">{eyebrow}</p>
        <h2 id={titleId}>{title}</h2>
      </div>
      <div className="workspace-header-right">{actions}</div>
    </div>
  );
}

export function CaseProgressCard({
  eyebrow,
  completed,
  total,
  action,
  emptyText = "No fields",
}: {
  eyebrow: string;
  completed: number;
  total: number;
  action?: ReactNode;
  emptyText?: string;
}) {
  return (
    <div className="case-submit-card" aria-label={`${eyebrow} progress`}>
      <div>
        <span className="eyebrow">{eyebrow}</span>
        {total > 0 ? (
          <>
            <strong>
              {completed}/{total}
            </strong>
            <small>{Math.max(0, total - completed)} field(s) left</small>
          </>
        ) : (
          <small>{emptyText}</small>
        )}
      </div>
      {action}
    </div>
  );
}
