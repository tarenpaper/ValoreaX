import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL?.trim();
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim();

// Missing configuration must never fall back to an unauthenticated dashboard.
export const supabase = url && key
  ? createClient(url, key, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: "pkce" },
    })
  : null;

export function authRedirect(recovery = false) {
  return `${window.location.origin}/${recovery ? "?auth=recovery" : ""}`;
}
