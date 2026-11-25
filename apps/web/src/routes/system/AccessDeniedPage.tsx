import { useAuthSession } from "../../auth/authSession";

interface DeniedCopy {
  heading: string;
  body: string;
  contactAdmin?: boolean;
  showSignOut?: boolean;
}

const COPY: Record<string, DeniedCopy> = {
  identity_not_rostered: {
    heading: "Access not set up",
    body: "You're signed in, but this account hasn't been added to the review platform yet. Ask an administrator to add your email to the roster.",
    contactAdmin: true,
  },
  account_disabled: {
    heading: "Account disabled",
    body: "This account has been disabled. Contact an administrator if you think this is a mistake.",
    contactAdmin: true,
    showSignOut: true,
  },
  session_unavailable: {
    heading: "Verification unavailable",
    body: "We couldn't verify your secure sign-in. Try again shortly, or contact support if it keeps happening.",
  },
  authentication_required: {
    heading: "Sign in required",
    body: "Your session isn't active. Access is managed through your organisation's password sign-in — sign in again to continue.",
  },
  unavailable: {
    heading: "Access check unavailable",
    body: "We couldn't confirm your access just now. Check your connection and try again.",
  },
};

const FALLBACK: DeniedCopy = {
  heading: "Access unavailable",
  body: "Your account can't open the review platform right now. Contact an administrator if you expected access.",
  contactAdmin: true,
};

export function AccessDeniedPage() {
  const session = useAuthSession();
  const copy = (session.deniedCode && COPY[session.deniedCode]) || FALLBACK;

  return (
    <section className="auth-page" aria-labelledby="access-denied-title">
      <div className="auth-card">
        <p className="eyebrow">Access</p>
        <h2 id="access-denied-title">{copy.heading}</h2>
        <p>{copy.body}</p>
        {copy.contactAdmin ? (
          <p className="muted">
            Access to the review platform is managed by a workspace administrator.
          </p>
        ) : null}
        <div className="auth-actions">
          <button className="primary-button" type="button" onClick={() => void session.reload()}>
            Check access again
          </button>
          {copy.showSignOut ? (
            <button className="text-button" type="button" onClick={() => void session.signOut()}>
              Sign out or switch account
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
