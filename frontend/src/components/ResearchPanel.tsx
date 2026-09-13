import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ResearchResponse } from "../types";
import { ErrorNote, Icon, Spinner } from "./ui";

/** Citation chips that scroll to their evidence record and expand every enclosing <details>. */
function EvidenceRefs({ ticker, ids }: { ticker: string; ids: string[] }) {
  return <span className="ml-2 inline-flex gap-1">{ids.map(id => <a className="text-primary hover:underline" href={`#research-${ticker}-${id}`} onClick={() => {
    let node: HTMLElement | null = document.getElementById(`research-${ticker}-${id}`);
    while (node) { if (node instanceof HTMLDetailsElement) node.open = true; node = node.parentElement; }
  }} key={id}>[{id}]</a>)}</span>;
}

export default function ResearchPanel({ ticker, assumptions = null, scope = "company" }: { ticker: string; assumptions?: Record<string, number> | null; scope?: "company" | "clinical" }) {
  const clinical = scope === "clinical";
  const citationKey = `${scope}-${ticker}`;
  const [question, setQuestion] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [result, setResult] = useState<ResearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  // Compare assumptions by value: re-running the DCF with identical inputs must not
  // trigger a second Gemini call.
  const assumptionsKey = JSON.stringify(assumptions);
  useEffect(() => {
    let active = true;
    setResult(null); setError(null);
    api.research(ticker, submitted, assumptionsKey ? JSON.parse(assumptionsKey) : null, scope)
      .then(data => { if (active) setResult(data); })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : "Research unavailable."); });
    return () => { active = false; };
  }, [ticker, attempt, submitted, assumptionsKey, scope]);
  return <section className="research-room relative overflow-hidden p-6 lg:p-9">
    <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3"><div className="agent-orb flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-white"><Icon name="token" size="base" /></div><div><h2 className="text-lg font-semibold">{clinical ? "Plutus Clinical Insights" : "Plutus Agent Room"}</h2><p className="mt-1 text-xs text-on-surface-variant">{clinical ? "Trial design, published findings, and clinical uncertainties explained" : "Gemini reasoning grounded in your company’s research evidence"}</p></div></div>
      <span className="rounded-full bg-surface-container px-3 py-1.5 font-mono text-[11px]">{result?.status === "ready" ? result.model : "Powered by Gemini"}</span>
    </div>
    {!result && !error && <Spinner label={clinical ? "Plutus is reviewing clinical evidence…" : "Gemini is analyzing the company evidence…"} />}
    {error && <><ErrorNote message={error} /><button className="mt-3 text-primary hover:underline" onClick={() => setAttempt(v => v + 1)}>Retry analysis</button></>}
    {result?.status === "needs_setup" && <p className="text-sm text-on-surface-variant">Gemini research is not connected yet. Configure the backend Gemini key to enable evidence-based insights.</p>}
    {result?.status === "ready" && <div className="space-y-4 text-sm leading-relaxed">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="rounded border border-outline-variant px-2 py-1 capitalize text-primary">{result.outlook.replaceAll("_", " ")} {clinical ? "clinical evidence" : "outlook"}</span>
        <span className="text-xs text-on-surface-variant">{result.model} · {new Date(result.generated_at).toLocaleString()}{result.cached ? " · Cached" : ""}</span>
      </div>
      <div className="rounded-2xl bg-surface-container-low p-5"><p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-secondary">Research synthesis</p><p className="font-editorial text-xl leading-relaxed lg:text-2xl">{result.summary}</p></div>
      <div className="grid gap-5 lg:grid-cols-2">
        {([[clinical ? 'What the evidence tells us' : 'Supporting factors', result.drivers], [clinical ? 'Safety and study limitations' : 'Risks and counterpoints', result.risks]] as const).map(([title, points]) => <div key={title}>
          <h3 className="mb-2 font-semibold">{title}</h3>
          <ul className="space-y-3">{points.map((point, i) => <li key={i}>{point.text}<EvidenceRefs ticker={citationKey} ids={point.evidence_ids} /></li>)}</ul>
          {!points.length && <p className="text-on-surface-variant">Insufficient evidence to identify factors.</p>}
        </div>)}
      </div>
      {result.tensions.length > 0 && <div className="rounded-2xl border border-outline-variant bg-surface-container-low p-5">
        <h3 className="font-semibold">{clinical ? "Unanswered clinical questions" : "Model tensions"}</h3>
        <p className="mt-1 text-xs text-on-surface-variant">{clinical ? "What the available studies cannot yet establish." : "Where the DCF and signal outputs disagree with the rest of the evidence. These are challenges to the models, not a recommendation."}</p>
        <ul className="mt-3 space-y-3">{result.tensions.map((point, i) => <li key={i}>{point.text}<EvidenceRefs ticker={citationKey} ids={point.evidence_ids} /></li>)}</ul>
      </div>}
      {result.limitations.length > 0 && <div><h3 className="font-semibold">Data limitations</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-on-surface-variant">{result.limitations.map((item, i) => <li key={i}>{item}</li>)}</ul></div>}
      <details className="border-t border-outline-variant pt-3"><summary className="cursor-pointer text-primary">Inspect evidence used ({result.evidence.length} records)</summary>
        <div className="mt-3 space-y-2">{result.evidence.map(item => <details id={`research-${citationKey}-${item.id}`} key={item.id} className="rounded border border-outline-variant p-2"><summary className="cursor-pointer">[{item.id}] {item.label}</summary><pre className="mt-2 whitespace-pre-wrap break-words text-xs text-on-surface-variant">{JSON.stringify(item.data, null, 2)}</pre></details>)}</div>
      </details>
      <p className="text-xs text-on-surface-variant">{clinical ? "AI interpretation, not medical or investment advice. Registry milestones do not establish treatment benefit or safety. Check the cited trial records; missing results remain unknown." : "AI-generated interpretation of the displayed evidence. It can make mistakes; evidence references do not guarantee factual accuracy. The DCF and signal shown here remain separate deterministic calculations — Gemini examines them, it does not produce the recommendation."}</p>
    </div>}
    <form className="mt-6 flex flex-col gap-3 rounded-2xl bg-surface-container p-2 pl-4 sm:flex-row sm:items-center" onSubmit={event => { event.preventDefault(); setSubmitted(question.trim()); setAttempt(value => value + 1); }}>
      <Icon name="auto_awesome" className="hidden text-secondary sm:inline-block" /><input aria-label="Ask Plutus a research question" maxLength={1000} value={question} onChange={event => setQuestion(event.target.value)} placeholder={clinical ? `Ask Plutus about ${ticker} endpoints, safety, or trial design…` : `Ask Plutus about ${ticker} financials, risks, or clinical catalysts…`} className="min-w-0 flex-1 bg-transparent py-2 text-sm outline-none" />
      <button type="submit" disabled={!result && !error || result?.status === "needs_setup"} className="flex items-center justify-center gap-2 rounded-full bg-ink px-6 py-3 text-sm font-semibold text-white disabled:opacity-40">Synthesize <Icon name="arrow_forward" /></button>
    </form>
    <div className="mt-3 flex flex-wrap items-center gap-2"><span className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Explore</span>{(clinical ? ["Explain the trial endpoints in plain English", "Are actual results posted, or only milestones?", "What safety and study-design gaps matter most?"] : ["What are the main risks?", "Assess the cash position", "Explain the analyst outlook"]).map(prompt => <button key={prompt} onClick={() => setQuestion(prompt)} className="rounded-full bg-surface-container-low px-3 py-1.5 text-xs text-on-surface-variant hover:bg-surface-container">{prompt}</button>)}</div>
  </section>;
}
