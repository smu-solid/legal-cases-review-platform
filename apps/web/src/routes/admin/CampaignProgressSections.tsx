import type {
  CampaignCaseProgressItem,
  CampaignProgressItem,
  ReviewerWorkloadResponse,
} from "../../api/types";
import { InfoTooltip } from "../../components/InfoTooltip";
import { ProgressBar } from "../../components/ProgressBar";
import { Spinner } from "../../components/Spinner";
import {
  AdminActionBar,
  AdminEmptyState,
  AdminMetricGrid,
  AdminSectionCard,
} from "../../components/admin/AdminLayout";

type ReviewerProgress = ReviewerWorkloadResponse["items"][number] & { reviewer_name: string };

export function CampaignProgressSection({
  progress,
  campaignReviewerRows,
  selectedReviewerIds,
}: {
  progress: CampaignProgressItem | null;
  campaignReviewerRows: ReviewerProgress[];
  selectedReviewerIds: ReadonlySet<string>;
}) {
  return (
    <AdminSectionCard eyebrow="Monitor" title="Campaign progress" titleId="progress-title">
      {!progress || progress.total_units === 0 ? (
        <AdminEmptyState quiet title="Not monitoring yet">
          <p>Monitoring starts after cases are loaded and assignments are published.</p>
        </AdminEmptyState>
      ) : progress.total_assignments === 0 ? (
        <AdminEmptyState quiet title="Cases loaded">
          <p>Cases loaded. Publish assignments to begin monitoring reviewer progress.</p>
        </AdminEmptyState>
      ) : (
        <AdminMetricGrid>
          <div className="metric-card">
            <span>Cases</span>
            <strong>{progress.cases_total}</strong>
          </div>
          <div className="metric-card">
            <span>
              Review units{" "}
              <InfoTooltip
                label="About: Review units"
                text="A review unit is the smallest independently reviewable thing inside a case -- one case-metadata field, citation, or cited-case/statute/appeal relation. A case is what the dataset supplies as one independent item; campaign progress is tracked per case, not per review unit."
              />
            </span>
            <strong>{progress.total_units}</strong>
          </div>
          <div className="metric-card">
            <span>
              Review-unit assignments{" "}
              <InfoTooltip
                label="About: Review-unit assignments"
                text="Live (review unit, reviewer) rows in this campaign -- the same granularity the publish result reports. Not the case-level 'Case assignments' figure in the assignment plan above."
              />
            </span>
            <strong>{progress.total_assignments}</strong>
          </div>
          <div className="metric-card">
            <span>Reviewers</span>
            <strong>{progress.reviewers_total}</strong>
          </div>
          <div className="metric-card">
            <span>Pending</span>
            <strong>{progress.unit_status_counts.pending}</strong>
          </div>
          <div className="metric-card">
            <span>In review</span>
            <strong>{progress.unit_status_counts.in_review}</strong>
          </div>
          <div className="metric-card">
            <span>Submitted</span>
            <strong>{progress.assignment_status_counts.submitted}</strong>
          </div>
          <div className="metric-card">
            <span>Adjudication</span>
            <strong>{progress.unit_status_counts.in_adjudication}</strong>
          </div>
          <div className="metric-card">
            <span>Completed</span>
            <strong>{progress.unit_status_counts.resolved}</strong>
          </div>
        </AdminMetricGrid>
      )}
      {progress && progress.cases_total > 0 ? (
        <div className="metric-card case-fully-complete-progress-card">
          <span>
            Cases fully complete{" "}
            <InfoTooltip
              label="About: Cases fully complete"
              text="A case counts as fully complete only once every reviewer actually assigned to it has explicitly submitted the case from their case-submit preview -- not merely because every field in it happens to already be submitted. This is a count of whole cases, not reviewer-case slots (see 'Cases reviewed, by reviewer' below)."
            />
          </span>
          <ProgressBar
            value={progress.cases_fully_complete_count}
            total={progress.cases_total}
            label="Cases fully complete"
          />
        </div>
      ) : null}
      {progress && progress.case_reviewer_slots_total > 0 ? (
        <div className="metric-card case-reviewer-progress-card">
          <span>
            Cases reviewed, by reviewer{" "}
            <InfoTooltip
              label="About: Cases reviewed, by reviewer"
              text="Every case is expected to be reviewed by each of this campaign's selected reviewers, so the total is cases x reviewers. A slot only fills once a reviewer explicitly submits the case from their case-submit preview -- not merely because every field in it happens to already be submitted."
            />
          </span>
          <ProgressBar
            value={progress.case_reviewer_completions}
            total={progress.case_reviewer_slots_total}
            label="Cases reviewed, by reviewer"
          />
        </div>
      ) : null}
      {campaignReviewerRows.length > 0 ? (
        <div className="table-wrap">
          <table aria-label="Reviewer coverage">
            <thead>
              <tr>
                <th scope="col">Reviewer</th>
                <th scope="col">On roster</th>
                <th scope="col">
                  Review-unit assignments{" "}
                  <InfoTooltip
                    label="About: Review-unit assignments"
                    text="Live work this reviewer currently holds, counted per review unit rather than per case -- the same granularity as the publish result. A reviewer holding one case with 5 in-scope fields shows 5 here. Released rows are excluded: those are units a rebalance moved to another reviewer, and they are counted in the Released column instead."
                  />
                </th>
                <th scope="col">Claimed</th>
                <th scope="col">Submitted</th>
                <th scope="col">Released</th>
              </tr>
            </thead>
            <tbody>
              {campaignReviewerRows.map((item) => (
                <tr key={item.reviewer_id}>
                  <td>{item.reviewer_name}</td>
                  <td>
                    {selectedReviewerIds.has(item.reviewer_id) ? (
                      "Yes"
                    ) : item.claimed_count + item.submitted_count > 0 ? (
                      <span className="chip">No — has access</span>
                    ) : (
                      "No"
                    )}
                  </td>
                  <td>{item.total_assignments}</td>
                  <td>{item.claimed_count}</td>
                  <td>{item.submitted_count}</td>
                  <td>{item.released_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </AdminSectionCard>
  );
}

export function CampaignCasesSection({
  cases,
  isLoading,
  isFetching,
  hasMore,
  onLoadMore,
}: {
  cases: CampaignCaseProgressItem[];
  isLoading: boolean;
  isFetching: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
}) {
  return (
    <AdminSectionCard eyebrow="Cases" title="Per-case progress" titleId="cases-title">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Case</th>
              <th scope="col">
                Field groups{" "}
                <InfoTooltip
                  label="About: Field groups"
                  text={
                    'Field groups organize the case-field values selected for review. "Case ' +
                    'metadata" includes fields such as case title, neutral citation, reported ' +
                    'citation, and suit number. Other groups ("Court, date & coram", ' +
                    '"Parties, lawyers & firms", "Cited cases", "Statutes cited", ' +
                    '"Appeal relations") cover court/hearing facts, representation, and the ' +
                    "corresponding evidence relations."
                  }
                />
              </th>
              <th scope="col">Units</th>
              <th scope="col">Assigned</th>
              <th scope="col">Submitted</th>
              <th scope="col">
                Reviewers done{" "}
                <InfoTooltip
                  label="About: Reviewers done"
                  text="How many of the reviewers assigned to this case have explicitly submitted it, out of how many are assigned. This case progresses (counts toward campaign completion) once every assigned reviewer has finished it."
                />
              </th>
              <th scope="col">Resolved</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((item) => (
              <tr key={item.case_id}>
                <td>{item.display_title}</td>
                <td>
                  <div className="chip-row">
                    {item.field_group_labels.map((label) => (
                      <span className="chip" key={label}>
                        {label}
                      </span>
                    ))}
                  </div>
                </td>
                <td>{item.unit_count}</td>
                <td>{item.assignment_count}</td>
                <td>{item.submitted_count}</td>
                <td>
                  {item.reviewers_completed_count}/{item.reviewers_assigned_count}
                </td>
                <td>{item.resolved_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {cases.length === 0 && !isLoading ? (
        <p className="muted">No cases in this campaign yet.</p>
      ) : null}
      {hasMore ? (
        <AdminActionBar>
          <button
            className="secondary-button"
            disabled={isFetching}
            type="button"
            onClick={onLoadMore}
          >
            {isFetching ? (
              <>
                <Spinner /> Loading…
              </>
            ) : (
              "Load more cases"
            )}
          </button>
        </AdminActionBar>
      ) : null}
    </AdminSectionCard>
  );
}
