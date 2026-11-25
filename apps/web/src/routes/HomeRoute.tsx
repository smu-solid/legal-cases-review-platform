import { Navigate } from "react-router-dom";

import type { MeResponse } from "../api/types";
import { useAuthSession } from "../auth/authSession";
import { AccessDeniedPage } from "./system/AccessDeniedPage";

// Map the backend `default_landing` role hint (`/admin` | `/adjudication` | `/reviewer`) plus the
// active tenant into the app's tenant-scoped route. Returns null for a rostered account with no
// actionable role, which lands on `/forbidden`.
function landingPath(me: MeResponse | null): string | null {
  const tenant = me?.active_tenant;
  const landing = me?.default_landing;
  if (!tenant || !landing) {
    return null;
  }

  switch (landing) {
    case "/admin":
      return `/t/${tenant}/admin`;
    case "/adjudication":
      return `/t/${tenant}/adjudication`;
    case "/reviewer":
      return `/t/${tenant}/review`;
    default:
      return null;
  }
}

export function HomeRoute() {
  const session = useAuthSession();

  if (session.status === "unknown") {
    return (
      <div className="notice" role="status">
        Checking your access...
      </div>
    );
  }

  if (session.status === "denied") {
    return <AccessDeniedPage />;
  }

  if (session.status === "authenticated") {
    return <Navigate to={landingPath(session.me) ?? "/forbidden"} replace />;
  }

  return <Navigate to="/sign-in" replace />;
}
