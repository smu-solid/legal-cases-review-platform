import { Link } from "react-router-dom";
import { AssignedCasesSection, AvailableCasesSection } from "./queue/ReviewerQueueSections";
import { useReviewerQueue } from "./queue/useReviewerQueue";

import { Spinner } from "../../components/Spinner";
import { CaseSubmitToast } from "./CaseSubmitToast";

export function ReviewerQueuePage() {
  const model = useReviewerQueue();
  const {
    tenantId,
    setCaseRefreshVersion,
    newCasesNotice,
    setNewCasesNotice,
    renderedAssignedTotalRef,
    lastNotifiedTotalRef,
    caseSubmitToast,
    campaignsQuery,
    campaign,
    queueError,
    hasError,
    cases,
    available,
    isLoading,
  } = model;

  return (
    <section className="queue-page" aria-labelledby="queue-title">
      <Link className="breadcrumb-back" to={`/t/${tenantId}/review`}>
        ← Back to your campaigns
      </Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Reviewer workspace</p>
          <h2 id="queue-title">{campaign?.campaign_name ?? "Campaign queue"}</h2>
        </div>
      </div>
      <CaseSubmitToast message={caseSubmitToast} />

      {newCasesNotice ? (
        <div className="notice compact" role="status">
          <p>
            {newCasesNotice.count} new case{newCasesNotice.count === 1 ? " was" : "s were"} added to
            this campaign — refresh to see {newCasesNotice.count === 1 ? "it" : "them"}.
          </p>
          <div className="action-row">
            <button
              className="secondary-button"
              type="button"
              onClick={() => {
                renderedAssignedTotalRef.current = newCasesNotice.latestTotal;
                lastNotifiedTotalRef.current = newCasesNotice.latestTotal;
                setNewCasesNotice(null);
                setCaseRefreshVersion((current) => current + 1);
                void campaignsQuery.refetch();
              }}
            >
              Refresh cases
            </button>
            <button
              className="secondary-button"
              type="button"
              onClick={() => setNewCasesNotice(null)}
            >
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      {isLoading ? (
        <div className="notice">
          <Spinner /> Loading your assigned work...
        </div>
      ) : null}
      {hasError ? (
        <div className="notice" role="alert">
          {queueError}
        </div>
      ) : null}

      {!hasError && cases.length > 0 ? <AssignedCasesSection {...model} /> : null}

      {!hasError && available.length > 0 ? <AvailableCasesSection {...model} /> : null}

      {!hasError && !isLoading && cases.length === 0 && available.length === 0 ? (
        <div className="page-panel">
          <h3>No items in this view.</h3>
          <p>New work will appear here when it is assigned or available to claim.</p>
        </div>
      ) : null}
    </section>
  );
}
