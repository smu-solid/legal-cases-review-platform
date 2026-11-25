import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiRequest } from "../../api/client";
export function SetPasswordPage({ activation }: { activation: boolean }) {
  const [params] = useSearchParams();
  const token = params.get("token") ?? params.get("reset_token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (password !== confirm) {
      setError("The passwords must match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const csrf = await apiRequest<{ csrf_token: string }>("/auth/csrf");
      await apiRequest(activation ? "/auth/activate" : "/auth/reset-password", {
        method: "POST",
        body: { token, password },
        csrfToken: csrf.csrf_token,
      });
      setPassword("");
      setConfirm("");
      setDone(true);
      window.history.replaceState(null, "", window.location.pathname);
    } catch {
      setError(
        "This link is invalid or expired, or the password does not meet the requirements. Contact your administrator if needed.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="auth-page">
      <form className="auth-card" onSubmit={submit}>
        <h2>{activation ? "Activate your account" : "Reset your password"}</h2>
        {done ? (
          <>
            <p role="status">Your password is saved.</p>
            <Link to="/sign-in">Sign in</Link>
          </>
        ) : (
          <>
            <label>
              New password
              <input
                type="password"
                autoComplete="new-password"
                minLength={12}
                maxLength={1024}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <label>
              Confirm password
              <input
                type="password"
                autoComplete="new-password"
                required
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </label>
            <p>Use at least 12 characters.</p>
            {error ? <p role="alert">{error}</p> : null}
            <button className="primary-button" type="submit" disabled={busy || !token}>
              {busy ? "Saving…" : "Save password"}
            </button>
          </>
        )}
      </form>
    </section>
  );
}
