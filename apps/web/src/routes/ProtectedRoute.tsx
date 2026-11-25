import type { PropsWithChildren } from "react";
import { Navigate } from "react-router-dom";

import { useAuthSession } from "../auth/authSession";
import { AccessDeniedPage } from "./system/AccessDeniedPage";

export function ProtectedRoute({ children }: PropsWithChildren) {
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

  if (session.status === "unauthenticated") {
    return <Navigate to="/sign-in" replace />;
  }

  return children;
}
