import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { listAdjudicationCampaigns } from "../../api/admin";
import { ApiError } from "../../api/client";
import { ProgressBar } from "../../components/ProgressBar";
import { Spinner } from "../../components/Spinner";

export function AdjudicationQueuePage() {
  const { tenantId = "" } = useParams();
  const queueQuery = useInfiniteQuery({
    queryKey: ["adjudication-campaigns", tenantId],
    queryFn: ({ pageParam }) => listAdjudicationCampaigns(tenantId, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: Boolean(tenantId),
    retry: false,
  });
  const queueError =
    queueQuery.error instanceof ApiError && queueQuery.error.status === 403
      ? "You are not authorized to adjudicate for this tenant."
      : "The adjudication campaigns could not be loaded. Retry in a moment.";
  const campaigns = queueQuery.data?.pages.flatMap((page) => page.campaigns) ?? [];

  return (
    <section className="admin-page" aria-labelledby="adjudication-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Adjudicator workspace</p>
          <h2 id="adjudication-title">Adjudication campaigns</h2>
          <p>Choose a campaign to review your waiting, in-progress, and finished cases.</p>
        </div>
      </div>
      {queueQuery.isLoading ? (
        <div className="notice">
          <Spinner /> Loading campaigns...
        </div>
      ) : null}
      {queueQuery.isError ? (
        <div className="notice" role="alert">
          {queueError}
        </div>
      ) : null}
      <div className="queue-list">
        {campaigns.map((campaign) => (
          <article className="queue-item case-queue-item" key={campaign.campaign_id}>
            <div className="case-queue-body">
              <p className="eyebrow">Adjudication campaign</p>
              <h3>{campaign.campaign_name}</h3>
              <p className="muted">
                <code>{campaign.campaign_key}</code>
              </p>
              <p className="muted">
                {campaign.finished_count}/{campaign.total_case_count} cases finished ·{" "}
                {campaign.in_progress_count} in progress · {campaign.waiting_count} waiting
                {campaign.not_required_count > 0
                  ? ` · ${campaign.not_required_count} not required from you`
                  : null}
              </p>
              <ProgressBar
                value={campaign.finished_count}
                total={campaign.total_case_count}
                label={`${campaign.campaign_name} adjudication progress`}
              />
            </div>
            <Link
              className="primary-button"
              to={`/t/${tenantId}/adjudication/campaigns/${campaign.campaign_id}`}
            >
              View cases
            </Link>
          </article>
        ))}
      </div>
      {queueQuery.hasNextPage ? (
        <button
          className="secondary-button"
          type="button"
          disabled={queueQuery.isFetchingNextPage}
          onClick={() => void queueQuery.fetchNextPage()}
        >
          {queueQuery.isFetchingNextPage ? "Loading..." : "Show more campaigns"}
        </button>
      ) : null}
      {!queueQuery.isLoading && !queueQuery.isError && !campaigns.length ? (
        <div className="page-panel">
          <h3>No adjudication campaigns</h3>
          <p>No authorized campaign work is available.</p>
        </div>
      ) : null}
    </section>
  );
}
