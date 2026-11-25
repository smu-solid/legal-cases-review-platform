import { useAuthSession } from "../../auth/authSession";

export function SessionExpiredPage() {
  const session = useAuthSession();

  return (
    <section className="page-panel" aria-labelledby="session-expired-title">
      <p className="eyebrow">Session</p>
      <h2 id="session-expired-title">Session expired</h2>
      <p>
        Your access needs to be checked again through your account before you continue reviewing
        assigned work.
      </p>
      <div className="auth-actions">
        <button className="secondary-button" type="button" onClick={() => void session.reload()}>
          Check access again
        </button>
        <button className="primary-button" type="button" onClick={() => void session.signOut()}>
          Sign in again
        </button>
      </div>
    </section>
  );
}
