import { useEffect, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "./supabase";
import AuthPage from "./AuthPage";

export default function AuthGate({ children }: { children: (session: Session) => ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [recovery, setRecovery] = useState(new URLSearchParams(window.location.search).get("auth") === "recovery");
  const [error, setError] = useState<string | null>(() => {
    const query = new URLSearchParams(window.location.search);
    const hash = new URLSearchParams(window.location.hash.slice(1));
    return query.has("error") || hash.has("error")
      ? "This sign-in link is invalid or expired. Please sign in or request a new password reset link."
      : null;
  });

  useEffect(() => {
    if (!supabase) { setLoading(false); return; }
    let active = true;
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, next) => {
      if (!active) return;
      setSession(next);
      setLoading(false);
      if (event === "PASSWORD_RECOVERY") setRecovery(true);
      if (event === "SIGNED_OUT") setRecovery(false);
    });
    void supabase.auth.getSession().then(({ data, error: sessionError }) => {
      if (!active) return;
      if (sessionError) setError("Your session could not be restored. Please sign in again.");
      setSession(data.session);
      setLoading(false);
    }).catch(() => {
      if (active) { setError("Unable to connect. Please try again."); setLoading(false); }
    });
    return () => { active = false; subscription.unsubscribe(); };
  }, []);

  if (loading) return <div className="flex min-h-screen items-center justify-center text-on-surface-variant" role="status">Opening your workspace…</div>;
  if (!supabase) return <AuthPage configured={false} />;
  if (recovery && session) return <AuthPage recovery onRecovered={() => {
    setRecovery(false);
    window.history.replaceState({}, "", "/");
  }} />;
  if (!session) return <AuthPage initialError={error} />;
  return <div key={session.user.id}>{children(session)}</div>;
}
