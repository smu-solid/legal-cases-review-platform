import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { hasCapability, useAuthSession } from "../auth/authSession";

// Reviewer pages render inside a focused, full-height shell (fixed header + footer, only the central
// region scrolls). A page injects its own footer action layer -- e.g. the case workspace's
// within-campaign Previous/Next navigation -- through this context; the brand line is always shown.
export interface AppLayoutOutletContext {
  setFooterSlot: (node: ReactNode) => void;
}

function roleSummary(
  canSeeAdmin: boolean,
  canSeeAdjudication: boolean,
  canSeeReviewQueue: boolean,
) {
  const roles = [
    ...(canSeeAdmin ? ["admin"] : []),
    ...(canSeeAdjudication ? ["adjudication"] : []),
    ...(canSeeReviewQueue ? ["reviewer"] : []),
  ];

  return roles.length ? roles.join(" / ") : "no workspace role";
}

export function AppLayout() {
  const session = useAuthSession();
  const location = useLocation();
  const [isAccountMenuOpen, setIsAccountMenuOpen] = useState(false);
  const [footerSlot, setFooterSlot] = useState<ReactNode>(null);
  const accountMenuRef = useRef<HTMLDetailsElement>(null);

  // Native <details> stays open on outside click and Escape; close it so the account menu
  // behaves like an accessible popover.
  useEffect(() => {
    if (!isAccountMenuOpen) {
      return;
    }

    function closeMenu() {
      accountMenuRef.current?.removeAttribute("open");
      setIsAccountMenuOpen(false);
    }

    function onPointerDown(event: PointerEvent) {
      if (accountMenuRef.current && !accountMenuRef.current.contains(event.target as Node)) {
        closeMenu();
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        closeMenu();
      }
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isAccountMenuOpen]);
  const tenantId = session.me?.active_tenant ?? null;
  const canSeeAdmin = hasCapability(session, [
    "can_administer",
    "can_manage_campaigns",
    "can_allocate",
  ]);
  const canSeeAdjudication = hasCapability(session, ["can_adjudicate", "can_administer"]);
  const canSeeReviewQueue = hasCapability(session, ["can_review"]);
  const authenticatedNavItems =
    session.status === "authenticated" && tenantId
      ? [
          ...(canSeeReviewQueue ? [{ to: `/t/${tenantId}/review`, label: "Reviewer queue" }] : []),
          ...(canSeeAdmin ? [{ to: `/t/${tenantId}/admin`, label: "Admin" }] : []),
          ...(canSeeAdjudication
            ? [{ to: `/t/${tenantId}/adjudication`, label: "Adjudication" }]
            : []),
        ]
      : [];
  const userLabel = session.me?.display_name || session.me?.email || "Signed in";
  const userEmail = session.me?.email ?? "Email unavailable";
  const accountSummary = roleSummary(canSeeAdmin, canSeeAdjudication, canSeeReviewQueue);

  // Reviewer routes (queue, campaign case list, case workspace) use the focused shell; the case
  // workspace additionally goes edge-to-edge and carries a footer case-nav layer. Adjudication's
  // campaign queues keep the ordinary shell; its case workspace uses the same focused boundary.
  const isAdjudicationWorkspace = /\/adjudication\/(?!campaigns\/)[^/]+$/.test(location.pathname);
  const isReviewerRoute = /\/review(\/|$)/.test(location.pathname) || isAdjudicationWorkspace;
  const isWorkspaceRoute = /\/review\/task\//.test(location.pathname) || isAdjudicationWorkspace;
  const showSidebar =
    session.status === "authenticated" && !isReviewerRoute && authenticatedNavItems.length > 0;
  const bodyClassName =
    session.status !== "authenticated"
      ? "app-body auth-only-layout"
      : showSidebar
        ? "app-body"
        : "app-body no-sidebar";

  return (
    <div className={isReviewerRoute ? "app-shell focused-shell" : "app-shell"}>
      <header className="topbar">
        <Link className="brand-link" to="/" aria-label="Show home page">
          <p className="eyebrow">Review Platform</p>
          <h1>Review Platform</h1>
        </Link>
        <div className="topbar-actions">
          {session.status === "authenticated" ? (
            <details
              className="account-menu"
              ref={accountMenuRef}
              onToggle={(event) => setIsAccountMenuOpen(event.currentTarget.open)}
            >
              <summary aria-label={`Account menu for ${userLabel}`}>
                <span>{userLabel}</span>
                <small>{accountSummary}</small>
              </summary>
              {isAccountMenuOpen ? (
                <div className="account-panel">
                  <div>
                    <p className="account-name">{userLabel}</p>
                    <p className="account-email">{userEmail}</p>
                  </div>
                  <p className="account-guidance">
                    Sign out to end this session, then sign in with another account to switch users.
                  </p>
                  <div className="account-actions">
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => void session.reload()}
                    >
                      Check access
                    </button>
                    <button
                      className="primary-button"
                      type="button"
                      onClick={() => void session.signOut()}
                    >
                      Sign out
                    </button>
                  </div>
                </div>
              ) : null}
            </details>
          ) : null}
        </div>
      </header>
      <div className={bodyClassName}>
        {showSidebar ? (
          <nav className="sidebar" aria-label="Primary navigation">
            {authenticatedNavItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        ) : null}
        {session.signOutError ? <p role="alert">{session.signOutError}</p> : null}
        <main
          className={isWorkspaceRoute ? "content content-workspace" : "content"}
          id="main-content"
        >
          <Outlet context={{ setFooterSlot } satisfies AppLayoutOutletContext} />
        </main>
      </div>
      {isReviewerRoute ? (
        <footer className="app-footer">
          {isWorkspaceRoute && footerSlot ? (
            <div className="app-footer-actions">{footerSlot}</div>
          ) : null}
          <div className="app-footer-brand">Review Platform</div>
        </footer>
      ) : null}
    </div>
  );
}
