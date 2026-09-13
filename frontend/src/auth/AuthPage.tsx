import { useState, type FormEvent } from "react";
import { authRedirect, supabase } from "./supabase";
import "./auth.css";

type Mode = "login" | "signup" | "forgot" | "reset";
const inputStyle = "auth-input";

export default function AuthPage({ configured = true, recovery = false, onRecovered, initialError = null }: {
  configured?: boolean; recovery?: boolean; onRecovered?: () => void; initialError?: string | null;
}) {
  const [mode, setMode] = useState<Mode>(recovery ? "reset" : "login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState(initialError);

  function switchMode(next: Mode) {
    setShowPassword(false); setMode(next); setPassword(""); setConfirm(""); setError(null); setMessage(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!supabase || busy) return;
    setError(null); setMessage(null);
    if ((mode === "signup" || mode === "reset") && password !== confirm) {
      setError("The passwords don’t match."); return;
    }
    setBusy(true);
    try {
      if (mode === "login") {
        const { error: authError } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
        if (authError) throw authError;
      } else if (mode === "signup") {
        const { data, error: authError } = await supabase.auth.signUp({
          email: email.trim(), password, options: { emailRedirectTo: authRedirect() },
        });
        if (authError) throw authError;
        if (!data.session) { setMessage("Check your email to confirm your account, then return here to sign in."); setPassword(""); setConfirm(""); }
      } else if (mode === "forgot") {
        const { error: authError } = await supabase.auth.resetPasswordForEmail(email.trim(), { redirectTo: authRedirect(true) });
        if (authError) throw authError;
        setMessage("If an account exists for that email, you’ll receive a password reset link. Open it in this browser.");
      } else {
        const { error: authError } = await supabase.auth.updateUser({ password });
        if (authError) throw authError;
        onRecovered?.();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally { setBusy(false); }
  }

  const heading = { login: "Welcome back", signup: "Create your account", forgot: "Reset your password", reset: "Choose a new password" }[mode];
  return (
    <div className="auth-page">
      <header className="auth-header">
        <a href="/" className="auth-brand" aria-label="ValoreaX home">
          <span className="auth-emblem" aria-hidden="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" /><path d="M12 3v6M12 15v6M3 12h6M15 12h6" />
            </svg>
          </span>
          <span><strong>ValoreaX</strong><small>Biotech Intelligence</small></span>
        </a>
      </header>
      <main className="auth-main">
        <section className="auth-card" aria-labelledby="auth-heading">
          <div className="auth-card-header">
            <h1 id="auth-heading">{configured ? heading : "Account setup pending"}</h1>
            <p>{!configured ? "Sign-in will be available once authentication is connected." : mode === "login" ? "Sign in to access clinical insights and educational equity research." : mode === "signup" ? "Keep your watchlist and research in your own workspace." : mode === "forgot" ? "We’ll email you a link to choose a new password." : "Use at least 12 characters for your new password."}</p>
          </div>
          {configured && <form onSubmit={submit} className="auth-form">
            {mode !== "reset" && <div>
              <label htmlFor="email" className="auth-label">Work email</label>
              <div className="auth-input-wrap">
                <input id="email" name="email" type="email" autoComplete="email" required maxLength={254} value={email} onChange={e => setEmail(e.target.value)} className={inputStyle} placeholder="analyst@bioventure.com" disabled={busy} />
                <span className="auth-input-icon" aria-hidden="true">@</span>
              </div>
            </div>}
            {mode !== "forgot" && <div>
              <div className="auth-label-row">
                <label htmlFor="password" className="auth-label">{mode === "reset" ? "New password" : "Password"}</label>
                {mode === "login" && <button type="button" onClick={() => switchMode("forgot")} disabled={busy} className="auth-link">Forgot password?</button>}
              </div>
              <div className="auth-input-wrap">
                <input id="password" name="password" type={showPassword ? "text" : "password"} autoComplete={mode === "login" ? "current-password" : "new-password"} required minLength={mode === "login" ? 1 : 12} maxLength={128} value={password} onChange={e => setPassword(e.target.value)} className={inputStyle} placeholder="••••••••••••" disabled={busy} aria-describedby={mode === "signup" ? "password-help" : undefined} />
                <button type="button" className="auth-reveal" onClick={() => setShowPassword(value => !value)} disabled={busy} aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="12" cy="12" r="3" /><path d="M2.458 12C3.732 7.943 7.523 5 12 5s8.268 2.943 9.542 7C20.268 16.057 16.477 19 12 19S3.732 16.057 2.458 12Z" />
                    {showPassword && <path d="m3 3 18 18" />}
                  </svg>
                </button>
              </div>
              {mode === "signup" && <p id="password-help" className="auth-help">At least 12 characters.</p>}
            </div>}
            {(mode === "signup" || mode === "reset") && <div>
              <label htmlFor="confirm" className="auth-label">Confirm password</label>
              <input id="confirm" name="confirm-password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={confirm} onChange={e => setConfirm(e.target.value)} className={inputStyle} disabled={busy} />
            </div>}
            {error && <p role="alert" className="auth-notice auth-error">{error}</p>}
            {message && <p role="status" className="auth-notice auth-success">{message}</p>}
            <button type="submit" disabled={busy} className="auth-submit">
              {busy ? "Please wait…" : { login: "Sign in to Workspace", signup: "Create account", forgot: "Send reset link", reset: "Save new password" }[mode]}
              {!busy && <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m14 5 7 7-7 7M21 12H3" /></svg>}
            </button>
          </form>}
          {configured && mode !== "reset" && <div className="auth-card-footer">
            {mode === "login" ? "New to ValoreaX? " : mode === "signup" ? "Already have an account? " : "Remember your password? "}
            <button type="button" disabled={busy} className="auth-link" onClick={() => switchMode(mode === "login" ? "signup" : "login")}>{mode === "login" ? "Create an account" : "Sign in"}</button>
          </div>}
        </section>
      </main>
      <footer className="auth-footer">
        <p>Healthcare Equity Research <span aria-hidden="true">·</span> Educational Use Only</p>
        <p>Powered by Plutus Autonomous</p>
      </footer>
    </div>
  );
}
