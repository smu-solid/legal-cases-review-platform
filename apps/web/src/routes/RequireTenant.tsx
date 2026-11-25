import type { PropsWithChildren } from "react";
import { Navigate, useParams } from "react-router-dom";

import { useAuthSession } from "../auth/authSession";
import { ForbiddenPage } from "./system/ForbiddenPage";

// Every `t/:tenantId/*` route is wrapped in this. A global `super_admin` may open any tenant (the
// backend already allows this via `allow_global_admin` on every tenant-scoped route), so this only
// guards non-global-admin accounts: if the URL's tenant is not one of theirs, redirect to `/` (which
// re-derives the correct tenant from `/me`'s `active_tenant`) instead of silently rendering an
// empty/403'd page. An account with zero tenant memberships and no global role sees a clear
// "not available for your role" state rather than a data page that can never load anything.
export function RequireTenant({ children }: PropsWithChildren) {
  const { tenantId } = useParams();
  const session = useAuthSession();
  const me = session.me;

  if (!me) {
    return children;
  }

  const isGlobalAdmin = me.global_capabilities.includes("global:admin");
  if (isGlobalAdmin) {
    return children;
  }

  const accessibleTenantIds = new Set(me.memberships.map((membership) => membership.tenant_id));
  if (tenantId && accessibleTenantIds.has(tenantId)) {
    return children;
  }

  if (accessibleTenantIds.size === 0) {
    return <ForbiddenPage />;
  }

  // Known but wrong tenant (stale link/bookmark, or a tenant this account was removed from) —
  // bounce to `/`, which re-derives the current accessible tenant from `/me` rather than showing an
  // empty or 403'd page under the stale id.
  return <Navigate to="/" replace />;
}
