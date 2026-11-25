import { Spinner } from "../../../components/Spinner";
import { AdminSectionCard } from "../../../components/admin/AdminLayout";
import {
  formatActivity,
  reviewerInviteErrorMessage,
  reviewerInviteSuccessMessage,
} from "../adminFormatters";
import type { useDashboardFormState } from "./useAdminDashboard";
import { useDashboardData } from "./useDashboardData";
import { useReviewerInvitation } from "./useReviewerInvitation";

export function ReviewerOnboardingSection({
  inviteMutation,
  handleInviteSubmit,
  inviteEmailError,
  inviteEmail,
  setInviteEmail,
  setInviteEmailError,
  rosterQuery,
  activeReviewers,
  pendingReviewers,
  inactiveReviewers,
  eligibleReviewers,
}: {
  inviteMutation: ReturnType<typeof useReviewerInvitation>["inviteMutation"];
  handleInviteSubmit: ReturnType<typeof useReviewerInvitation>["handleInviteSubmit"];
  inviteEmailError: ReturnType<typeof useDashboardFormState>["inviteEmailError"];
  inviteEmail: ReturnType<typeof useDashboardFormState>["inviteEmail"];
  setInviteEmail: ReturnType<typeof useDashboardFormState>["setInviteEmail"];
  setInviteEmailError: ReturnType<typeof useDashboardFormState>["setInviteEmailError"];
  rosterQuery: ReturnType<typeof useDashboardData>["rosterQuery"];
  activeReviewers: ReturnType<typeof useDashboardData>["activeReviewers"];
  pendingReviewers: ReturnType<typeof useDashboardData>["pendingReviewers"];
  inactiveReviewers: ReturnType<typeof useDashboardData>["inactiveReviewers"];
  eligibleReviewers: ReturnType<typeof useDashboardData>["eligibleReviewers"];
}) {
  const sectionToExtract = (
    <AdminSectionCard
      eyebrow="People"
      title="Reviewer onboarding"
      titleId="people-title"
      id="admin-people"
      trailing={
        inviteMutation.isPending ? (
          <span className="status-chip">
            <Spinner /> Sending
          </span>
        ) : null
      }
    >
      <div className="admin-panel-grid">
        <div className="admin-subpanel">
          <h4>Invite reviewer</h4>
          <p className="muted">
            Add a reviewer’s email to send a private activation link. They choose a password before
            becoming eligible for allocation. A sent invitation means the mail sender accepted the
            message; it does not guarantee inbox delivery.
          </p>
          <form className="form-stack" onSubmit={handleInviteSubmit}>
            {inviteMutation.isError ? (
              <div className="form-error" role="alert">
                {reviewerInviteErrorMessage(inviteMutation.error)}
              </div>
            ) : null}
            {inviteMutation.isSuccess ? (
              <div className="notice" role="status">
                {reviewerInviteSuccessMessage(inviteMutation.data?.invitation_email)}
              </div>
            ) : null}
            <label>
              Reviewer email
              <input
                autoComplete="email"
                aria-invalid={inviteEmailError ? "true" : "false"}
                name="invite_email"
                type="email"
                value={inviteEmail}
                onChange={(event) => {
                  setInviteEmail(event.target.value);
                  setInviteEmailError(null);
                }}
              />
            </label>
            {inviteEmailError ? (
              <div className="form-error" role="alert">
                {inviteEmailError}
              </div>
            ) : null}
            <button
              className="primary-button"
              disabled={inviteMutation.isPending || !inviteEmail.trim()}
              type="submit"
            >
              Add reviewer
            </button>
          </form>
          <details className="help-disclosure">
            <summary>How reviewer access works</summary>
            <p>
              Add a reviewer to send an activation link. Once they choose a password, their account
              becomes active and eligible for allocation. Administrators can suspend access or send
              a password-reset link.
            </p>
          </details>
        </div>

        <div className="admin-subpanel">
          <div className="pane-heading">
            <div>
              <h4>Reviewer roster</h4>
              <p className="muted">
                Invited reviewers can be assigned cases once they set a password using their
                activation link.
              </p>
            </div>
            {rosterQuery.isLoading ? (
              <span className="status-chip">
                <Spinner /> Loading
              </span>
            ) : null}
          </div>

          <div className="roster-group">
            <div className="roster-group-head">
              <h5>Active reviewers</h5>
              <span className="status-chip">{activeReviewers.length}</span>
            </div>
            {activeReviewers.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Reviewer</th>
                      <th scope="col">Roles</th>
                      <th scope="col">Eligible</th>
                      <th scope="col">Assigned</th>
                      <th scope="col">Submitted</th>
                      <th scope="col">Claimed</th>
                      <th scope="col">Released</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeReviewers.map((reviewer) => (
                      <tr key={reviewer.membership_id}>
                        <td>{reviewer.display_name}</td>
                        <td>{reviewer.roles.join(", ")}</td>
                        <td>{reviewer.eligible ? "Yes" : "No"}</td>
                        <td>{reviewer.total_assignments}</td>
                        <td>{reviewer.submitted_count}</td>
                        <td>{reviewer.claimed_count}</td>
                        <td>{reviewer.released_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">No active reviewers yet.</p>
            )}
          </div>

          <div className="roster-group">
            <div className="roster-group-head">
              <h5>Pending / invited reviewers</h5>
              <span className="status-chip">{pendingReviewers.length}</span>
            </div>
            {pendingReviewers.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Reviewer</th>
                      <th scope="col">Roster status</th>
                      <th scope="col">Roles</th>
                      <th scope="col">Account activated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pendingReviewers.map((reviewer) => (
                      <tr key={reviewer.membership_id}>
                        <td>{reviewer.display_name}</td>
                        <td>{reviewer.roster_status.replaceAll("_", " ")}</td>
                        <td>{reviewer.roles.join(", ")}</td>
                        <td>{formatActivity(reviewer.first_seen_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">
                No pending invitations. Invited reviewers appear here until they set a password.
              </p>
            )}
          </div>

          {inactiveReviewers.length > 0 ? (
            <div className="roster-group">
              <div className="roster-group-head">
                <h5>Disabled / ineligible reviewers</h5>
                <span className="status-chip">{inactiveReviewers.length}</span>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Reviewer</th>
                      <th scope="col">Roster status</th>
                      <th scope="col">Roles</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inactiveReviewers.map((reviewer) => (
                      <tr key={reviewer.membership_id}>
                        <td>{reviewer.display_name}</td>
                        <td>{reviewer.roster_status.replaceAll("_", " ")}</td>
                        <td>{reviewer.roles.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          {eligibleReviewers.length === 0 && !rosterQuery.isLoading ? (
            <div className="notice compact" role="status">
              No reviewers are eligible for assignments yet.
            </div>
          ) : null}
        </div>
      </div>
    </AdminSectionCard>
  );
  return sectionToExtract;
}
