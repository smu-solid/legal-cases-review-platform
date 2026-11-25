import type { PropsWithChildren } from "react";
import { Navigate } from "react-router-dom";

import type { CapabilityFlags } from "../api/types";
import { hasCapability, useAuthSession } from "../auth/authSession";

// Route-level authorization from `/me` capabilities. Visibility/routing only — the server enforces
// the real authorization on roles. A missing capability is a genuine wrong-role case → `/forbidden`.
export function RequireCapability({
  anyOf,
  children,
}: PropsWithChildren<{ anyOf: (keyof CapabilityFlags)[] }>) {
  const session = useAuthSession();

  if (!hasCapability(session, anyOf)) {
    return <Navigate to="/forbidden" replace />;
  }

  return children;
}
