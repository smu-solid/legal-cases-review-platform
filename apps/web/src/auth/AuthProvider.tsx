import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type PropsWithChildren } from "react";

import { ApiError, apiRequest } from "../api/client";
import type { CsrfResponse, MeResponse } from "../api/types";
import { AuthContext, type AuthSession } from "./authSession";

function deniedCodeFromError(error: unknown): string {
  if (error instanceof ApiError && error.body && typeof error.body === "object") {
    const code = (error.body as { code?: unknown }).code;
    if (typeof code === "string") {
      return code;
    }
  }
  // A verified identity refused entry with no code, or a transport failure. Fall back to a generic
  // "try again" state rather than pretending the user is unauthenticated.
  return "unavailable";
}

export function AuthProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthSession["status"]>("unknown");
  const [csrfToken, setCsrfToken] = useState<string | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const [deniedCode, setDeniedCode] = useState<string | null>(null);
  // Last identity id observed, to clear the query cache when the account changes under the app.
  const lastIdentityRef = useRef<string | null>(null);

  const applySession = useCallback(
    (nextMe: MeResponse) => {
      if (lastIdentityRef.current && lastIdentityRef.current !== nextMe.id) {
        queryClient.clear();
      }
      lastIdentityRef.current = nextMe.id;
      setMe(nextMe);
      setDeniedCode(null);
      setStatus("authenticated");
    },
    [queryClient],
  );

  const loadSession = useCallback(async () => {
    try {
      const currentUser = await apiRequest<MeResponse>("/auth/me");
      const csrf = await apiRequest<CsrfResponse>("/auth/csrf");
      setCsrfToken(csrf.csrf_token);

      // The shell renders only for an active app user. `/me` returns 200 only for allowed
      // identities, but guard defensively on the status field too.
      if (currentUser.status && currentUser.status !== "active") {
        setMe(null);
        setDeniedCode(currentUser.status === "suspended" ? "account_disabled" : currentUser.status);
        setStatus("denied");
        return;
      }

      applySession(currentUser);
    } catch (error) {
      setMe(null);
      if (error instanceof ApiError && error.status === 401) {
        setDeniedCode(null);
        setStatus("unauthenticated");
        return;
      }
      setDeniedCode(deniedCodeFromError(error));
      setStatus("denied");
    }
  }, [applySession]);

  useEffect(() => {
    let active = true;
    void (async () => {
      if (active) {
        await loadSession();
      }
    })();
    return () => {
      active = false;
    };
  }, [loadSession]);

  const reload = useCallback(async () => {
    setStatus("unknown");
    await loadSession();
  }, [loadSession]);

  const signOut = useCallback(async () => {
    setSignOutError(null);
    try {
      await apiRequest<unknown>("/auth/logout", { method: "POST", csrfToken });
    } catch {
      setSignOutError("Sign out failed. Check your connection and try again.");
      return;
    }
    queryClient.clear();
    lastIdentityRef.current = null;
    setCsrfToken(null);
    setMe(null);
    setDeniedCode(null);
    setStatus("unauthenticated");
  }, [csrfToken, queryClient]);

  const value = useMemo<AuthSession>(
    () => ({ status, csrfToken, me, deniedCode, signOut, signOutError, reload }),
    [csrfToken, deniedCode, me, reload, signOut, signOutError, status],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
