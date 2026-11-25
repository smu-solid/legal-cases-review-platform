import { useAuthSession } from "../../auth/authSession";

export function ForbiddenPage() {
  const session = useAuthSession();

  return (
    <section className="page-panel" aria-labelledby="forbidden-title">
      <p className="eyebrow">Access</p>
      <h2 id="forbidden-title">Not available for your role</h2>
      <p>
        You are signed in, but your current role does not include this workspace. Access is managed
        by your administrator.
      </p>
      <div className="auth-actions">
        <button className="secondary-button" type="button" onClick={() => void session.reload()}>
          Check access again
        </button>
        <button className="primary-button" type="button" onClick={() => void session.signOut()}>
          Sign out or switch account
        </button>
      </div>
    </section>
  );
}
