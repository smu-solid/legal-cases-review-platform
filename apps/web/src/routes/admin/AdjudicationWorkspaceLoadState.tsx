import { Link } from "react-router-dom";

import { ApiError } from "../../api/client";
import { Spinner } from "../../components/Spinner";

export function AdjudicationWorkspaceLoadState({
  loading,
  error,
  tenantId,
  campaignId,
}: {
  loading: boolean;
  error: Error | null;
  tenantId: string;
  campaignId: string;
}) {
  if (loading)
    return (
      <div className="notice">
        <Spinner /> Loading full case...
      </div>
    );
  if (!error) return null;
  const forbidden = error instanceof ApiError && error.status === 403;
  const missing = error instanceof ApiError && error.status === 404;
  return (
    <section className="reviewer-workspace">
      <div className="notice" role="alert">
        {forbidden
          ? "This adjudication is not assigned to your account."
          : missing
            ? "This case is no longer open. Return to the campaign queue to refresh its status."
            : "This adjudication could not be loaded."}
      </div>
      <Link to={`/t/${tenantId}/adjudication/campaigns/${campaignId}`}>
        Return to campaign cases
      </Link>
    </section>
  );
}
