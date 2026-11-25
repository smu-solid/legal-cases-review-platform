import { AdminMetricGrid } from "../../../components/admin/AdminLayout";
import { useAdminDashboard } from "./useAdminDashboard";

export function DashboardOverview({
  overview,
  campaigns,
}: {
  overview: ReturnType<typeof useAdminDashboard>["overview"];
  campaigns: ReturnType<typeof useAdminDashboard>["campaigns"];
}) {
  const sectionToExtract = (
    <AdminMetricGrid>
      <div className="overview-card">
        <span>Cases</span>
        <strong>{overview.totalCases}</strong>
        <small>{campaigns.length === 1 ? "1 campaign" : `${campaigns.length} campaigns`}</small>
      </div>
      <div className="overview-card">
        <span>Review units</span>
        <strong>{overview.totalUnits}</strong>
        <small>Case-field items across all campaigns</small>
      </div>
      <div className="overview-card">
        <span>Pending</span>
        <strong>{overview.pending}</strong>
        <small>Not yet in review</small>
      </div>
      <div className="overview-card">
        <span>Assigned</span>
        <strong>{overview.totalAssignments}</strong>
        <small>{overview.inReview} units in review</small>
      </div>
      <div className="overview-card">
        <span>Claimed</span>
        <strong>{overview.claimed}</strong>
        <small>In progress</small>
      </div>
      <div className="overview-card">
        <span>Submitted</span>
        <strong>{overview.submitted}</strong>
        <small>Reviewer decisions</small>
      </div>
      <div className="overview-card">
        <span>Adjudication</span>
        <strong>{overview.inAdjudication}</strong>
        <small>Units awaiting resolution</small>
      </div>
      <div className="overview-card">
        <span>Completed</span>
        <strong>{overview.completed}</strong>
        <small>Resolved units</small>
      </div>
    </AdminMetricGrid>
  );
  return sectionToExtract;
}
