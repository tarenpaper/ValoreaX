import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Catalyst } from "../types";
import { Badge, ErrorNote } from "./ui";

const EVENT_TYPES = [
  "pdufa",
  "adcomm",
  "phase_readout",
  "trial_start",
  "trial_completion",
  "approval",
  "crl",
  "label_expansion",
  "other",
];
const OUTCOMES = ["pending", "positive", "negative", "mixed", "withdrawn"];
const PHASES = ["Preclinical", "Phase 1", "Phase 2", "Phase 3", "Filed", "Approved"];

const OUTCOME_STYLE: Record<string, string> = {
  positive: "border-long/40 bg-long/10 text-long",
  negative: "border-short/40 bg-short/10 text-short",
  mixed: "border-watch/40 bg-watch/10 text-watch",
  withdrawn: "border-edge bg-edge/40 text-muted",
  pending: "border-accent/40 bg-accent/10 text-accent",
};

const EMPTY = {
  drug_program: "",
  event_type: "pdufa",
  indication: "",
  trial_phase: "Filed",
  expected_date: "",
  outcome: "pending",
  source_url: "",
  notes: "",
};

export default function CatalystTimeline({ ticker }: { ticker: string }) {
  const [items, setItems] = useState<Catalyst[]>([]);
  const [form, setForm] = useState({ ...EMPTY });
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const res = await api.listCatalysts(ticker);
      setItems(res.catalysts);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker]);

  async function create() {
    if (!form.drug_program.trim()) {
      setError("Drug/program is required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = { ...form };
      for (const k of ["indication", "trial_phase", "source_url", "notes", "expected_date"]) {
        if (!payload[k]) delete payload[k];
      }
      await api.createCatalyst(ticker, payload);
      setForm({ ...EMPTY });
      setAdding(false);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function setOutcome(c: Catalyst, outcome: string) {
    await api.updateCatalyst(c.id, { outcome });
    await refresh();
  }

  async function remove(id: number) {
    await api.deleteCatalyst(id);
    await refresh();
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button
          onClick={() => setAdding((a) => !a)}
          className="rounded-md border border-edge px-2.5 py-1 text-xs text-slate-300 hover:border-accent"
        >
          {adding ? "Cancel" : "+ Add catalyst"}
        </button>
      </div>

      {adding && (
        <div className="grid grid-cols-2 gap-2 rounded-md border border-edge bg-ink/40 p-3 sm:grid-cols-3">
          <Input label="Drug / program *" value={form.drug_program} onChange={(v) => setForm({ ...form, drug_program: v })} />
          <Input label="Indication" value={form.indication} onChange={(v) => setForm({ ...form, indication: v })} />
          <Select label="Event type" value={form.event_type} options={EVENT_TYPES} onChange={(v) => setForm({ ...form, event_type: v })} />
          <Select label="Phase" value={form.trial_phase} options={PHASES} onChange={(v) => setForm({ ...form, trial_phase: v })} />
          <Input label="Expected date" type="date" value={form.expected_date} onChange={(v) => setForm({ ...form, expected_date: v })} />
          <Select label="Outcome" value={form.outcome} options={OUTCOMES} onChange={(v) => setForm({ ...form, outcome: v })} />
          <Input label="Source URL" value={form.source_url} onChange={(v) => setForm({ ...form, source_url: v })} />
          <Input label="Notes" value={form.notes} onChange={(v) => setForm({ ...form, notes: v })} className="sm:col-span-2" />
          <div className="col-span-2 sm:col-span-3">
            <button
              onClick={create}
              disabled={busy}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-ink disabled:opacity-50"
            >
              {busy ? "Saving…" : "Save catalyst"}
            </button>
          </div>
        </div>
      )}

      {error && <ErrorNote message={error} />}

      {items.length === 0 ? (
        <p className="text-xs text-muted">No catalysts yet. Add clinical/FDA events manually.</p>
      ) : (
        <ol className="relative space-y-3 border-l border-edge pl-4">
          {items.map((c) => (
            <li key={c.id} className="relative">
              <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-accent" />
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-muted">
                      {c.expected_date ?? "TBD"}
                    </span>
                    <span className="text-sm font-semibold text-slate-100">{c.drug_program}</span>
                    <Badge className="border-edge text-muted">{c.event_type}</Badge>
                    {c.trial_phase && (
                      <Badge className="border-edge text-slate-400">{c.trial_phase}</Badge>
                    )}
                  </div>
                  {c.indication && <p className="text-xs text-muted">{c.indication}</p>}
                  {c.notes && <p className="mt-0.5 text-[11px] text-slate-500">{c.notes}</p>}
                  {c.source_url && (
                    <a
                      href={c.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[11px] text-accent hover:underline"
                    >
                      source ↗
                    </a>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <select
                    value={c.outcome}
                    onChange={(e) => setOutcome(c, e.target.value)}
                    className={`rounded border px-1.5 py-0.5 text-[11px] ${OUTCOME_STYLE[c.outcome]}`}
                  >
                    {OUTCOMES.map((o) => (
                      <option key={o} value={o} className="bg-ink text-slate-200">
                        {o}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => remove(c.id)}
                    className="text-xs text-muted hover:text-short"
                    title="Delete"
                  >
                    ✕
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Input({
  label,
  value,
  onChange,
  type = "text",
  className = "",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  className?: string;
}) {
  return (
    <label className={`block ${className}`}>
      <span className="text-[11px] text-muted">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-0.5 w-full rounded-md border border-edge bg-ink px-2 py-1.5 text-sm outline-none focus:border-accent"
      />
    </label>
  );
}

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-0.5 w-full rounded-md border border-edge bg-ink px-2 py-1.5 text-sm outline-none focus:border-accent"
      >
        {options.map((o) => (
          <option key={o} value={o} className="bg-ink">
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}
