import { useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Basket } from "../types";
import { Icon } from "./ui";

/** Anything with a ticker and a name can be a basket member. */
export type BasketCandidate = { ticker: string; name: string };

/**
 * Baskets: named groups whose name is an anagram of the members' initials — MANGO, FAANG.
 *
 * Clicking a card makes that basket the watchlist. The name is checked against the
 * initials on the server; this component mirrors the same rule while you type so the
 * feedback is immediate, but the server's answer is the one that counts.
 */

/** The letters a company can stand for: its name's initial and its ticker's. */
function initialsFor(name: string, ticker: string): Set<string> {
  const letters = new Set<string>();
  for (const value of [name, ticker]) {
    const first = (value ?? "").match(/[a-zA-Z]/);
    if (first) letters.add(first[0].toUpperCase());
  }
  return letters;
}

function nameLetters(name: string): string[] {
  return (name.match(/[a-zA-Z]/g) ?? []).map((c) => c.toUpperCase());
}

/** Can every letter be served by a distinct company? Backtracking, at most 7 members. */
function canSpell(letters: string[], candidates: Set<string>[], used: boolean[]): boolean {
  if (letters.length === 0) return true;
  const [letter, ...rest] = letters;
  for (let i = 0; i < candidates.length; i += 1) {
    if (!used[i] && candidates[i].has(letter)) {
      used[i] = true;
      if (canSpell(rest, candidates, used)) return true;
      used[i] = false;
    }
  }
  return false;
}

export function checkName(name: string, members: BasketCandidate[]): string | null {
  const letters = nameLetters(name);
  if (letters.length === 0) return "Name it with letters, like MANGO.";
  if (letters.length !== members.length) {
    return `${name.toUpperCase()} has ${letters.length} letters but you picked ${members.length}.`;
  }
  const candidates = members.map((m) => initialsFor(m.name, m.ticker));
  const orphan = letters.find((l) => !candidates.some((c) => c.has(l)));
  if (orphan) return `Nothing you picked starts with ${orphan}.`;
  if (!canSpell(letters, candidates, members.map(() => false))) {
    return "One company would have to cover two letters — pick another.";
  }
  return null;
}

export default function BasketCards({
  baskets,
  companies,
  onChanged,
}: {
  baskets: Basket[];
  /** Everything the account holds, watched or not — a basket can be built from any of them. */
  companies: BasketCandidate[];
  onChanged: () => Promise<void> | void;
}) {
  const [building, setBuilding] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chosen = useMemo(
    () =>
      picked
        .map((t) => companies.find((c) => c.ticker === t))
        .filter((c): c is BasketCandidate => !!c),
    [picked, companies],
  );
  const localReason = chosen.length ? checkName(name, chosen) : "Pick the companies first.";

  function toggle(ticker: string) {
    setPicked((prev) =>
      prev.includes(ticker) ? prev.filter((t) => t !== ticker) : [...prev, ticker],
    );
  }

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between border-b border-outline-variant pb-2">
        <div>
          <h2 className="font-label-caps text-label-caps uppercase tracking-wider text-on-surface-variant">
            Baskets
          </h2>
          <p className="mt-0.5 font-data-sm text-[10px] text-on-surface-variant">
            Name spells the members’ initials. Click one to load it into the watchlist.
          </p>
        </div>
        <button
          onClick={() => {
            setBuilding((b) => !b);
            setError(null);
          }}
          className="flex items-center gap-1 rounded-sm bg-primary-container px-3 py-1 font-data-tabular text-data-tabular text-on-primary-container transition hover:opacity-90"
        >
          <Icon name={building ? "close" : "add"} size="xs" /> {building ? "Cancel" : "New Basket"}
        </button>
      </div>

      {error && (
        <p className="rounded-sm border border-error-container bg-error/5 px-3 py-2 font-data-sm text-[10px] text-error">
          {error}
        </p>
      )}

      {building && (
        <div className="space-y-3 rounded-sm border border-outline-variant bg-surface-container p-3">
          <div>
            <p className="mb-1.5 font-label-caps text-[9px] uppercase text-on-surface-variant">
              1 · Pick companies ({chosen.length})
            </p>
            <div className="flex flex-wrap gap-1.5">
              {companies.map((c) => {
                const on = picked.includes(c.ticker);
                return (
                  <button
                    key={c.ticker}
                    onClick={() => toggle(c.ticker)}
                    title={c.name}
                    className={`rounded-full border px-2.5 py-1 font-data-tabular text-[10px] transition ${
                      on
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-outline-variant bg-surface text-on-surface-variant hover:text-on-surface"
                    }`}
                  >
                    {c.ticker}
                    <span className="ml-1 opacity-60">
                      {[...initialsFor(c.name, c.ticker)].sort().join("/")}
                    </span>
                  </button>
                );
              })}
              {companies.length === 0 && (
                <p className="font-data-sm text-[10px] text-on-surface-variant">
                  Add a company first — baskets are built from what you already hold.
                </p>
              )}
            </div>
          </div>

          <div>
            <p className="mb-1.5 font-label-caps text-[9px] uppercase text-on-surface-variant">
              2 · Name it
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="MANGO"
                maxLength={32}
                className="w-40 rounded-sm border border-outline-variant bg-background px-2 py-1 font-data-tabular text-data-tabular uppercase tracking-widest text-on-surface focus:border-primary focus:outline-none"
              />
              <button
                disabled={busy || !!localReason}
                onClick={() =>
                  run(async () => {
                    await api.createBasket(name.trim().toUpperCase(), picked);
                    setPicked([]);
                    setName("");
                    setBuilding(false);
                  })
                }
                className="rounded-sm bg-primary-container px-3 py-1 font-data-tabular text-data-tabular font-semibold text-on-primary disabled:opacity-40"
              >
                {busy ? "Saving…" : "Save basket"}
              </button>
              <span
                className={`font-data-sm text-[10px] ${localReason ? "text-caution" : "text-primary"}`}
              >
                {localReason ?? `${name.toUpperCase()} works.`}
              </span>
            </div>
          </div>
        </div>
      )}

      {baskets.length === 0 && !building ? (
        <p className="rounded-sm border border-dashed border-outline-variant px-4 py-6 text-center font-data-sm text-[10px] text-on-surface-variant">
          No baskets yet. Build one from the companies you hold — the name has to spell their
          initials.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {baskets.map((basket) => {
            const incomplete = basket.members.some((m) => !m.available);
            return (
              <div
                key={basket.id}
                className={`group rounded-2xl border p-3 transition ${
                  basket.active
                    ? "border-primary/50 bg-primary/5"
                    : "border-outline-variant bg-surface hover:border-outline"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <button
                    disabled={busy || incomplete}
                    onClick={() => run(() => api.activateBasket(basket.id))}
                    className="text-left disabled:opacity-60"
                    title={incomplete ? "Some companies are missing" : `Load ${basket.name}`}
                  >
                    <span
                      className={`font-display-ticker text-[20px] uppercase tracking-widest ${
                        basket.active ? "text-primary" : "text-on-surface"
                      }`}
                    >
                      {basket.name}
                    </span>
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => run(() => api.deleteBasket(basket.id))}
                    title="Delete this basket (the companies are kept)"
                    className="rounded-sm p-1 text-on-surface-variant opacity-0 transition hover:text-error group-hover:opacity-100 focus:opacity-100"
                  >
                    <Icon name="delete" size="xs" />
                  </button>
                </div>

                <div className="mt-2 flex flex-wrap gap-1">
                  {basket.members.map((m) => (
                    <span
                      key={m.ticker}
                      title={m.name ?? "No longer in your workspace"}
                      className={`rounded-sm border px-1.5 py-0.5 font-data-tabular text-[10px] ${
                        m.available
                          ? "border-outline-variant text-on-surface-variant"
                          : "border-error-container text-error"
                      }`}
                    >
                      {m.ticker}
                    </span>
                  ))}
                </div>

                <p className="mt-2 font-data-sm text-[10px] text-on-surface-variant">
                  {incomplete
                    ? "Some companies are no longer in your workspace."
                    : basket.active
                      ? "Currently loaded"
                      : `${basket.size} companies · click to load`}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
