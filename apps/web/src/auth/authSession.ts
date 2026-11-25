import { createContext, useContext } from "react";

import type { CapabilityFlags, MeResponse } from "../api/types";

export type AuthStatus = "unknown" | "authenticated" | "unauthenticated" | "denied";

export interface AuthSession {
  status: AuthStatus;
  me: MeResponse | null;
  // Backend RFC7807 `code` for a `denied` state (e.g. `identity_not_rostered`, `account_disabled`,
  // `account_disabled`). Null unless `status === "denied"`.
  deniedCode: string | null;
  csrfToken: string | null;
  signOut(): Promise<void>;
  signOutError?: string | null;
  // Re-derive the session from `/me`. Clears the query cache if the identity changed.
  reload(): Promise<void>;
}

export const placeholderSession: AuthSession = {
  status: "unknown",
  me: null,
  deniedCode: null,
  csrfToken: null,
  signOut: async () => undefined,
  reload: async () => undefined,
};

export const AuthContext = createContext<AuthSession>(placeholderSession);

export function useAuthSession() {
  return useContext(AuthContext);
}

// Client-side capability read (visibility/routing only; the server still enforces on roles).
export function hasCapability(session: AuthSession, anyOf: (keyof CapabilityFlags)[]) {
  const capabilities = session.me?.capabilities;
  if (!capabilities) {
    return false;
  }

  return anyOf.some((flag) => capabilities[flag]);
}
