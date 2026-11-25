import { useState } from "react";
import { Link } from "react-router-dom";
import { Spinner } from "../../components/Spinner";
import type { WorkspaceSourceView } from "../../components/WorkspaceSourcePane";
import { ReviewerWorkspaceView } from "./workspace/ReviewerWorkspaceView";
import { useReviewerWorkspace } from "./workspace/useReviewerWorkspace";

type SourceView = WorkspaceSourceView;

export function ReviewerWorkspacePage() {
  // Text stays the default; Document citation selection requires an exact text projection.
  const [sourceView, setSourceView] = useState<SourceView>("text");
  const model = useReviewerWorkspace(sourceView, setSourceView);
  const { tenantId, bundleQuery, bundle } = model;

  if (!bundle) {
    return (
      <section className="reviewer-workspace" aria-labelledby="workspace-title">
        <div className="page-panel">
          <p className="eyebrow">Reviewer workspace</p>
          <h2 id="workspace-title">Review task</h2>
          {bundleQuery.isLoading ? (
            <p>
              <Spinner /> Loading grouped review bundle...
            </p>
          ) : (
            <p>Review task content is not available for this assignment.</p>
          )}
          {bundleQuery.isError ? (
            <div className="notice" role="alert">
              This review task could not be loaded right now. Retry in a moment, or contact an
              administrator if the problem continues.
            </div>
          ) : null}
          <Link className="secondary-button inline-action" to={`/t/${tenantId}/review`}>
            Back to queue
          </Link>
        </div>
      </section>
    );
  }

  return <ReviewerWorkspaceView {...model} bundle={bundle} />;
}
