import { useInfiniteQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import { listReviewerCampaignQueue } from "../../api/reviewer";
import type { ReviewerCampaignSummary } from "../../api/types";
import { ProgressBar } from "../../components/ProgressBar";
import { Spinner } from "../../components/Spinner";
import { CaseSubmitToast } from "./CaseSubmitToast";
import { useCaseSubmitToast } from "./useCaseSubmitToast";

// The reviewer-campaign queue is keyset-paginated server-side (see queue.py); each "Show more"
// fetches the next page via the returned cursor. Same pattern backs the campaign case list.
const CAMPAIGN_PAGE_SIZE = 12;

// Horizontal campaign card, mirroring the case cards on the campaign case-list page: a compact
// body (name, own-work case counts, progress bar) beside a single "Open campaign queue" action.
function CampaignCard({
  campaign,
  onOpen,
}: {
  campaign: ReviewerCampaignSummary;
  onOpen: () => void;
}) {
  const total = campaign.not_started_count + campaign.in_progress_count + campaign.completed_count;

  return (
    <article className="queue-item case-queue-item">
      <div className="case-queue-body">
        <p className="eyebrow">Campaign</p>
        <h3>{campaign.campaign_name}</h3>
        <p className="muted">
          <code>{campaign.campaign_key}</code>
        </p>
        <p className="muted">
          {campaign.completed_count}/{total} cases completed · {campaign.in_progress_count} in
          progress · {campaign.not_started_count} not started
        </p>
        <ProgressBar
          value={campaign.completed_count}
          total={total}
          label={`Campaign progress for ${campaign.campaign_name}`}
        />
      </div>
      <button className="primary-button" type="button" onClick={onOpen}>
        Open campaign queue
      </button>
    </article>
  );
}

export function ReviewerCampaignQueuePage() {
  const { tenantId = "" } = useParams();
  const navigate = useNavigate();
  // Brief success banner surfaced when a final case submit auto-navigated here (no campaignId on
  // the case route to return to a specific campaign's case list -- see CaseSubmitToast).
  const caseSubmitToast = useCaseSubmitToast();

  // Distinct from the case-list page's single-page ["reviewer-campaign-queue", tenantId] lookup so
  // the two query shapes never collide in the cache; the "" prefix still matches its invalidation.
  const campaignsQuery = useInfiniteQuery({
    queryKey: ["reviewer-campaign-queue", tenantId, "infinite"],
    queryFn: ({ pageParam }) =>
      listReviewerCampaignQueue(tenantId, { cursor: pageParam, limit: CAMPAIGN_PAGE_SIZE }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? (lastPage.next_cursor ?? undefined) : undefined,
    enabled: Boolean(tenantId),
    retry: false,
  });

  const campaigns = campaignsQuery.data?.pages.flatMap((page) => page.campaigns ?? []) ?? [];
  const errorMessage =
    campaignsQuery.error instanceof ApiError && campaignsQuery.error.status === 403
      ? "You are not assigned reviewer access for this tenant."
      : "Your campaign queue could not be loaded right now. Retry in a moment, or contact an administrator if the problem continues.";

  return (
    <section className="queue-page" aria-labelledby="queue-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Reviewer workspace</p>
          <h2 id="queue-title">Your assigned campaigns</h2>
        </div>
      </div>
      <CaseSubmitToast message={caseSubmitToast} />

      {campaignsQuery.isLoading ? (
        <div className="notice">
          <Spinner /> Loading your campaigns...
        </div>
      ) : null}
      {campaignsQuery.isError ? (
        <div className="notice" role="alert">
          {errorMessage}
        </div>
      ) : null}

      <div className="queue-list">
        {campaigns.map((campaign) => (
          <CampaignCard
            campaign={campaign}
            key={campaign.campaign_id}
            onOpen={() => navigate(`/t/${tenantId}/review/campaigns/${campaign.campaign_id}`)}
          />
        ))}
      </div>

      {campaignsQuery.hasNextPage ? (
        <div className="action-row">
          <button
            className="secondary-button"
            type="button"
            disabled={campaignsQuery.isFetchingNextPage}
            onClick={() => campaignsQuery.fetchNextPage()}
          >
            {campaignsQuery.isFetchingNextPage ? "Loading..." : "Show more campaigns"}
          </button>
        </div>
      ) : null}

      {campaigns.length === 0 && !campaignsQuery.isLoading && !campaignsQuery.isError ? (
        <div className="page-panel">
          <h3>No campaigns assigned to you yet.</h3>
          <p>When an administrator assigns you to a campaign, it will appear here.</p>
        </div>
      ) : null}
    </section>
  );
}
