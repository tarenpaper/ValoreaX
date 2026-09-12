import { useState, type FormEvent } from "react";
import { authRedirect, supabase } from "./supabase";

type Mode = "login" | "signup" | "forgot" | "reset";
const inputStyle = "w-full rounded-md border border-outline-variant bg-background px-3 py-3 text-base text-on-surface outline-none focus:border-primary focus:ring-1 focus:ring-primary";

export default function AuthPage({ configured = true, recovery = false, onRecovered, initialError = null }: {
  configured?: boolean; recovery?: boolean; onRecovered?: () => void; initialError?: string | null;
}) {
  const [mode, setMode] = useState<Mode>(recovery ? "reset" : "login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState(initialError);

  function switchMode(next: Mode) {
    setMode(next); setPassword(""); setConfirm(""); setError(null); setMessage(null);
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
    <main className="flex min-h-screen items-center justify-center bg-background px-5 py-12 text-on-surface">
      <div className="w-full max-w-md">
        <a href="/" className="mb-9 inline-flex items-center gap-3 text-xl font-semibold tracking-tight">
          <span className="flex h-10 w-10 items-center justify-center rounded-md border border-primary/40 bg-primary/10 font-mono text-primary" aria-hidden="true">V</span>
          ValoreaX
        </a>
        <section className="rounded-xl border border-outline-variant bg-surface-container-low p-6 shadow-xl sm:p-8">
          <h1 className="text-2xl font-semibold tracking-tight">{configured ? heading : "Account setup pending"}</h1>
          <p className="mt-2 text-base leading-relaxed text-on-surface-variant">
            {!configured ? "Sign-in will be available once authentication is connected." : mode === "login" ? "Sign in to your personal research workspace." : mode === "signup" ? "Keep your watchlist and research in your own workspace." : mode === "forgot" ? "We’ll email you a link to choose a new password." : "Use at least 12 characters for your new password."}
          </p>
          {configured && <form onSubmit={submit} className="mt-7 space-y-5">
            {mode !== "reset" && <div>
              <label htmlFor="email" className="mb-2 block text-sm font-medium">Email address</label>
              <input id="email" type="email" autoComplete="email" required maxLength={254} value={email} onChange={e => setEmail(e.target.value)} className={inputStyle} placeholder="you@example.com" disabled={busy} />
            </div>}
            {mode !== "forgot" && <div>
              <label htmlFor="password" className="mb-2 block text-sm font-medium">{mode === "reset" ? "New password" : "Password"}</label>
              <input id="password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} required minLength={mode === "login" ? 1 : 12} maxLength={128} value={password} onChange={e => setPassword(e.target.value)} className={inputStyle} disabled={busy} aria-describedby={mode === "signup" ? "password-help" : undefined} />
              {mode === "signup" && <p id="password-help" className="mt-2 text-sm text-on-surface-variant">At least 12 characters.</p>}
            </div>}
            {(mode === "signup" || mode === "reset") && <div>
              <label htmlFor="confirm" className="mb-2 block text-sm font-medium">Confirm password</label>
              <input id="confirm" type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={confirm} onChange={e => setConfirm(e.target.value)} className={inputStyle} disabled={busy} />
            </div>}
            {error && <p role="alert" className="rounded-md border border-error/30 bg-error/10 p-3 text-sm text-error">{error}</p>}
            {message && <p role="status" className="rounded-md border border-primary/30 bg-primary/10 p-3 text-sm leading-relaxed text-primary">{message}</p>}
            <button type="submit" disabled={busy} className="w-full rounded-md bg-primary px-4 py-3 text-base font-semibold text-on-primary transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary disabled:opacity-50">
              {busy ? "Please wait…" : { login: "Sign in", signup: "Create account", forgot: "Send reset link", reset: "Save new password" }[mode]}
            </button>
            {mode === "login" && <button type="button" onClick={() => switchMode("forgot")} disabled={busy} className="block w-full py-1 text-sm text-primary hover:underline">Forgot password?</button>}
          </form>}
          {configured && mode !== "reset" && <div className="mt-6 border-t border-outline-variant pt-5 text-center text-sm text-on-surface-variant">
            {mode === "login" ? "New to ValoreaX? " : mode === "signup" ? "Already have an account? " : "Remember your password? "}
            <button type="button" disabled={busy} className="font-medium text-primary hover:underline" onClick={() => switchMode(mode === "login" ? "signup" : "login")}>{mode === "login" ? "Create an account" : "Sign in"}</button>
          </div>}
        </section>
        <p className="mt-6 text-center text-sm text-on-surface-variant">Healthcare equity research · Educational use only</p>
      </div>
    </main>
  );
}
