import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { apiRequest } from "../../api/client";
import { useAuthSession } from "../../auth/authSession";

export function SignInPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const session = useAuthSession();
  const navigate = useNavigate();
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const csrf = await apiRequest<{ csrf_token: string }>("/auth/csrf");
      await apiRequest("/auth/login", {
        method: "POST",
        body: { email, password },
        csrfToken: csrf.csrf_token,
      });
      setPassword("");
      await session.reload();
      navigate("/", { replace: true });
    } catch {
      setError("Sign-in failed. Check your email and password, then try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="auth-page">
      <form className="auth-card" onSubmit={submit}>
        <p className="eyebrow">Review Platform</p>
        <h2>Sign in</h2>
        <p>Use the account provided by your administrator.</p>
        <label>
          Email
          <input
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error ? <p role="alert">{error}</p> : null}
        <button className="primary-button" disabled={busy} type="submit">
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p>
          To activate an invited account or reset your password, use the link sent by your
          administrator.
        </p>
      </form>
    </section>
  );
}
