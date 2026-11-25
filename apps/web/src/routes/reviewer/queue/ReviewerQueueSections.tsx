import { useState } from "react";
import type { ReviewerCaseQueueItem, ReviewQueueItem } from "../../../api/types";
import { ProgressBar } from "../../../components/ProgressBar";
import { Spinner } from "../../../components/Spinner";
import type { AvailableCaseGroup } from "./queueState";
import {
  CASE_PAGE_SIZES,
  formatCaseTitle,
  pageWindow,
  STATUS_LABEL,
  storeCasePageSize,
} from "./queueState";
import type { useReviewerQueue } from "./useReviewerQueue";

type QueueModel = ReturnType<typeof useReviewerQueue>;

function CaseCard({ item, onOpen }: { item: ReviewerCaseQueueItem; onOpen: () => void }) {
  return (
    <article className="queue-item case-queue-item">
      <div className="case-queue-body">
        <p className="eyebrow">
          Case{" "}
          <span className={`status-chip status-${item.status}`}>{STATUS_LABEL[item.status]}</span>
        </p>
        <h3>{formatCaseTitle(item)}</h3>
        <p className="muted">
          {item.fields_submitted}/{item.fields_assigned} fields submitted
        </p>
        <ProgressBar
          value={item.fields_submitted}
          total={item.fields_assigned}
          label={`Case progress for ${item.case_title}`}
        />
      </div>
      <button className="primary-button" type="button" onClick={onOpen}>
        Open case
      </button>
    </article>
  );
}

function AvailableCaseCard({
  group,
  isClaiming,
  claimError,
  onClaimCase,
  onClaimField,
  onOpenField,
}: {
  group: AvailableCaseGroup;
  isClaiming: boolean;
  claimError: string | null;
  onClaimCase: () => void;
  onClaimField: (item: ReviewQueueItem) => void;
  onOpenField: (item: ReviewQueueItem) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasClaimableField = group.items.some((item) => !item.assignment_id);

  return (
    <article className="queue-item case-queue-item available-case-group">
      <div>
        <p className="eyebrow">Case · {group.items.length} field(s) available</p>
        <h3>{group.displayTitle}</h3>
        {claimError ? (
          <p className="notice compact" role="alert">
            {claimError}
          </p>
        ) : null}
        <button
          type="button"
          className="link-button"
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? "Hide fields" : "Show fields"}
        </button>
        {expanded ? (
          <ul className="available-case-field-list">
            {group.items.map((item) => (
              <li key={item.review_unit_id}>
                <span>{item.safe_field_label}</span>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={isClaiming}
                  onClick={() => (item.assignment_id ? onOpenField(item) : onClaimField(item))}
                >
                  {item.assignment_id ? "Open task" : "Claim task"}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {hasClaimableField ? (
        <button
          className="primary-button"
          type="button"
          disabled={isClaiming}
          onClick={onClaimCase}
        >
          {isClaiming ? (
            <>
              <Spinner /> Claiming...
            </>
          ) : (
            "Claim entire case"
          )}
        </button>
      ) : null}
    </article>
  );
}

export function AssignedCasesSection({
  assignedCaseTotal,
  isPageLoading,
  currentPage,
  pageCases,
  openCase,
  casePageSize,
  setCasePageSize,
  reviewerId,
  pageRangeStart,
  pageRangeEnd,
  totalCasePages,
  setCurrentPage,
}: QueueModel) {
  return (
    <div>
      <div className="section-heading-row">
        <h3 className="section-heading">
          Your assigned cases{assignedCaseTotal !== null ? ` (${assignedCaseTotal})` : ""}
        </h3>
      </div>
      <div className="queue-list" aria-busy={isPageLoading}>
        {isPageLoading ? (
          <div className="pager-loading">
            <Spinner /> Loading page {currentPage + 1}…
          </div>
        ) : (
          pageCases.map((item) => (
            <CaseCard item={item} key={item.case_id} onOpen={() => openCase(item)} />
          ))
        )}
      </div>
      <nav className="pager" aria-label="Assigned cases pages">
        <div className="pager-summary">
          <label className="page-size-field">
            Cases per page
            <select
              value={casePageSize}
              onChange={(event) => {
                const next = Number(event.target.value);
                setCasePageSize(next);
                storeCasePageSize(reviewerId, next);
              }}
            >
              {CASE_PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="pager-nav">
          <p className="pager-status">
            Showing <strong>{pageRangeStart}</strong>–<strong>{pageRangeEnd}</strong>
            {assignedCaseTotal !== null ? (
              <>
                {" "}
                of <strong>{assignedCaseTotal}</strong>
              </>
            ) : null}
          </p>
          {totalCasePages > 1 ? (
            <div className="pager-controls">
              <button
                className="pager-button"
                type="button"
                disabled={currentPage === 0}
                onClick={() => setCurrentPage((page) => Math.max(0, page - 1))}
              >
                ‹ Prev
              </button>
              {pageWindow(currentPage + 1, totalCasePages).map((page, index) =>
                page === "ellipsis" ? (
                  <span className="pager-gap" key={`gap-${index}`} aria-hidden="true">
                    …
                  </span>
                ) : (
                  <button
                    className={`pager-button${page === currentPage + 1 ? " is-current" : ""}`}
                    type="button"
                    key={page}
                    aria-current={page === currentPage + 1 ? "page" : undefined}
                    aria-label={`Page ${page}`}
                    onClick={() => setCurrentPage(page - 1)}
                  >
                    {page}
                  </button>
                ),
              )}
              <button
                className="pager-button"
                type="button"
                disabled={currentPage + 1 >= totalCasePages}
                onClick={() => setCurrentPage((page) => Math.min(totalCasePages - 1, page + 1))}
              >
                Next ›
              </button>
            </div>
          ) : null}
        </div>
      </nav>
    </div>
  );
}

export function AvailableCasesSection({
  availableGroups,
  claimingCaseId,
  caseClaimErrors,
  claimEntireCase,
  claimMutation,
  navigate,
  tenantId,
  campaignId,
  availableQuery,
  setAvailableCursor,
}: QueueModel) {
  return (
    <div>
      <h3 className="section-heading">Available to claim</h3>
      <div className="queue-list">
        {availableGroups.map((group) => (
          <AvailableCaseCard
            group={group}
            key={group.caseId}
            isClaiming={claimingCaseId === group.caseId}
            claimError={caseClaimErrors[group.caseId] ?? null}
            onClaimCase={() => void claimEntireCase(group)}
            onClaimField={(item) => claimMutation.mutate(item)}
            onOpenField={(item) =>
              navigate(`/t/${tenantId}/review/task/${item.assignment_id}?campaignId=${campaignId}`)
            }
          />
        ))}
      </div>
      {availableQuery.data?.has_more ? (
        <div className="action-row">
          <button
            className="secondary-button"
            type="button"
            disabled={availableQuery.isFetching}
            onClick={() => setAvailableCursor(availableQuery.data?.next_cursor ?? null)}
          >
            {availableQuery.isFetching ? (
              <>
                <Spinner /> Loading...
              </>
            ) : (
              "Load more"
            )}
          </button>
        </div>
      ) : null}
    </div>
  );
}
