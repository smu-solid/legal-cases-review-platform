import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { listAdjudicationCampaignCases } from "../../api/admin";
import { ApiError } from "../../api/client";
import type { AdjudicationCampaignCaseItem } from "../../api/types";
import { ProgressBar } from "../../components/ProgressBar";
import { Spinner } from "../../components/Spinner";
import { AdjudicationFieldProgressDetails } from "./AdjudicationFieldProgressDetails";

const statuses = ["all", "in_progress", "waiting", "finished"] as const;
type Status = (typeof statuses)[number];

function formatCaseTitle(item: AdjudicationCampaignCaseItem) {
  return (
    [item.neutral_citation_display, item.case_title, item.reported_citation_display]
      .filter((part): part is string => Boolean(part && part.trim()))
      .join(" · ") || item.case_title
  );
}

function Progress({ item }: { item: AdjudicationCampaignCaseItem }) {
  if (item.progress.personal_responsibility_fields === 0) {
    return null;
  }
  return (
    <ProgressBar
      value={item.progress.completed_responsibility_fields}
      total={item.progress.personal_responsibility_fields}
      label={`${item.case_title} adjudication progress`}
    />
  );
}

export function AdjudicationCampaignCasesPage() {
  const { tenantId = "", campaignId = "" } = useParams();
  const [search, setSearch] = useSearchParams();
  const rawStatus = search.get("status") ?? "all";
  const status: Status = statuses.includes(rawStatus as Status) ? (rawStatus as Status) : "all";
  useEffect(() => {
    if (rawStatus !== status) setSearch({}, { replace: true });
  }, [rawStatus, setSearch, status]);
  const casesQuery = useInfiniteQuery({
    queryKey: ["adjudication-campaign-cases", tenantId, campaignId, status],
    queryFn: ({ pageParam }) =>
      listAdjudicationCampaignCases(tenantId, campaignId, status, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: Boolean(tenantId && campaignId),
    retry: false,
  });
  const error =
    casesQuery.error instanceof ApiError && casesQuery.error.status === 403
      ? "You are not authorized for this adjudication campaign."
      : "The campaign cases could not be loaded. Retry in a moment.";
  const firstPage = casesQuery.data?.pages[0];
  const counts = firstPage?.counts;
  const caseItems = casesQuery.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <section className="admin-page" aria-labelledby="campaign-cases-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Adjudication campaign</p>
          <h2 id="campaign-cases-title">{firstPage?.campaign.campaign_name ?? "Loading cases"}</h2>
        </div>
        <Link className="secondary-button" to={`/t/${tenantId}/adjudication`}>
          All campaigns
        </Link>
      </div>
      <nav className="adjudication-status-tabs" aria-label="Filter cases by status">
        {statuses.map((value) => (
          <button
            className={status === value ? "secondary-button is-active" : "secondary-button"}
            key={value}
            type="button"
            aria-pressed={status === value}
            onClick={() => setSearch(value === "all" ? {} : { status: value })}
          >
            {value.replace("_", " ")} {counts ? `(${counts[value]})` : ""}
          </button>
        ))}
      </nav>
      {casesQuery.isLoading ? (
        <div className="notice">
          <Spinner /> Loading cases...
        </div>
      ) : null}
      {casesQuery.isError ? (
        <div className="notice" role="alert">
          {error}
        </div>
      ) : null}
      <div className="queue-list">
        {caseItems.map((item) => (
          <article
            className={`queue-item adjudication-case-card status-${item.status}`}
            key={item.case_id}
          >
            <div>
              <p className="eyebrow">{item.status.replace("_", " ")}</p>
              <h3>{formatCaseTitle(item)}</h3>
              <p className="muted">{item.status_reason}</p>
              <Progress item={item} />
              <AdjudicationFieldProgressDetails item={item} />
            </div>
            {item.workspace_adjudication_id ? (
              <Link
                className={
                  item.workspace_mode === "read_only" ? "secondary-button" : "primary-button"
                }
                to={`/t/${tenantId}/adjudication/${item.workspace_adjudication_id}?campaignId=${campaignId}`}
              >
                {item.workspace_mode === "read_only" ? "View" : "Open"}
              </Link>
            ) : (
              <span className="status-chip">
                {item.status === "waiting" ? "Waiting" : "Not required"}
              </span>
            )}
          </article>
        ))}
      </div>
      {casesQuery.hasNextPage ? (
        <button
          className="secondary-button"
          type="button"
          disabled={casesQuery.isFetchingNextPage}
          onClick={() => void casesQuery.fetchNextPage()}
        >
          {casesQuery.isFetchingNextPage ? "Loading..." : "Show more cases"}
        </button>
      ) : null}
      {!casesQuery.isLoading && !casesQuery.isError && !caseItems.length ? (
        <div className="page-panel">
          <h3>No matching cases</h3>
          <p>Choose another status.</p>
        </div>
      ) : null}
    </section>
  );
}
