import { useState } from "react";
import { Icon } from "../components/ui";
import "./landing.css";

const tools = [
  { number: "01", icon: "biotech", title: "Understand the pipeline", text: "Explore clinical milestones, trial design, and the evidence behind a company’s drug programs. Ask Plutus to explain what the findings mean." },
  { number: "02", icon: "account_balance", title: "See what supports the value", text: "Bring SEC financials, cash runway, and drug-by-drug valuations together. Explore company-specific WACC and the assumptions behind the numbers." },
  { number: "03", icon: "monitoring", title: "Put your thesis in context", text: "Follow catalysts and news, organize a personal watchlist, and explore historical buy-and-hold outcomes against SPY and XLV." },
];

function Brand() {
  return <a className="landing-brand" href="/" aria-label="ValoreaX home"><span className="landing-emblem" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><circle cx="12" cy="12" r="3" /><path d="M12 3v6M12 15v6M3 12h6M15 12h6" /></svg></span><span>ValoreaX<span className="landing-brand-caption">BIOTECH INTELLIGENCE</span></span></a>;
}

export default function Landing() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  function toggleTheme() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try { localStorage.setItem("valoreax-theme", next ? "dark" : "light"); } catch { /* Theme still works without storage. */ }
  }
  return <div className="landing-page">
    <a href="#main" className="landing-skip">Skip to content</a>
    <header className="landing-nav landing-width">
      <Brand />
      <nav className="landing-nav-links" aria-label="Main navigation"><a href="#why">Why ValoreaX</a><a href="#tools">The workspace</a><a href="#approach">Our approach</a></nav>
      <div className="landing-nav-actions"><button type="button" className="landing-theme" onClick={toggleTheme} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}><Icon name={dark ? "light_mode" : "dark_mode"} /></button><a className="landing-signin" href="/?auth=login">Sign in <Icon name="arrow_outward" /></a></div>
    </header>
    <main id="main">
      <section className="landing-hero landing-width" aria-labelledby="hero-title">
        <div className="landing-hero-copy"><p className="landing-eyebrow"><span className="landing-status-dot" /> A clearer view of biotech</p>
          <h1 id="hero-title">The science.<br />The signals.<br /><em>The bigger picture.</em></h1>
          <p className="landing-intro">Biotech research lives at the intersection of clinical evidence and company economics. ValoreaX brings both into one workspace, so you can build a thesis with more context.</p>
          <div className="landing-hero-actions"><a className="landing-button" href="/?auth=signup">Create your workspace <Icon name="arrow_forward" /></a><a className="landing-text-link" href="#tools">Explore the tools <Icon name="arrow_downward" /></a></div>
          <p className="landing-small-note">Your account. Your watchlist. Your research.</p>
        </div>
        <div className="landing-preview-wrap">
          <div className="landing-preview" aria-label="Illustrative ValoreaX research workspace">
            <div className="landing-preview-bar"><span><span className="landing-status-dot" /> RESEARCH WORKSPACE</span><Icon name="more_horiz" /></div>
            <div className="landing-preview-heading"><div><p className="landing-eyebrow">Company overview</p><h2>From evidence<br />to understanding.</h2></div><span className="landing-preview-badge"><Icon name="biotech" /> Biotech</span></div>
            <div className="landing-preview-metrics"><div><span>COMPANY ECONOMICS</span><strong>Cash runway</strong><small>Understand the funding horizon</small></div><div><span>SUM OF THE PARTS</span><strong>Drug-by-drug value</strong><small>Inspect each assumption</small></div></div>
            <div className="landing-preview-chart"><div><span className="landing-eyebrow">A thesis, in context</span><span className="landing-chart-legend"><i /> Company <i /> Benchmark</span></div><svg viewBox="0 0 440 110" role="img" aria-label="Illustrative comparison chart; no actual returns shown"><defs><linearGradient id="landing-chart-fill" x1="0" y1="0" x2="0" y2="1"><stop stopColor="currentColor" stopOpacity=".15" /><stop offset="1" stopColor="currentColor" stopOpacity="0" /></linearGradient></defs><path d="M0 25H440M0 65H440M0 105H440" className="landing-chart-grid" /><path d="M0 95L30 92L60 99L90 76L120 82L150 69L180 78L210 57L240 64L270 42L300 50L330 32L360 44L390 18L420 27L440 10V110H0Z" fill="url(#landing-chart-fill)" /><path d="M0 99L40 95L80 91L120 85L160 88L200 76L240 72L280 70L320 64L360 57L400 56L440 48" className="landing-chart-benchmark" /><path d="M0 95L30 92L60 99L90 76L120 82L150 69L180 78L210 57L240 64L270 42L300 50L330 32L360 44L390 18L420 27L440 10" fill="none" stroke="currentColor" strokeWidth="2.5" /></svg></div>
            <div className="landing-preview-agent"><span className="landing-agent-icon"><Icon name="auto_awesome" /></span><div><strong>Plutus research insights</strong><p>Connect clinical evidence, valuation assumptions, and the questions that deserve a closer look.</p></div><Icon name="arrow_outward" /></div>
            <p className="landing-preview-label">Illustrative workspace · no live company data shown</p>
          </div><span className="landing-preview-caption">01 / THE RESEARCH, CONNECTED</span>
        </div>
      </section>
      <div className="landing-sources landing-width"><p>Built around evidence you can inspect</p><div><span>SEC filings</span><span>Clinical trial records</span><span>Market history</span><span>AI-assisted synthesis</span></div></div>
      <section id="why" className="landing-why landing-width" aria-labelledby="why-title"><p className="landing-eyebrow">Why we built ValoreaX</p><div><h2 id="why-title">A promising trial is only<br /><em>part of the story.</em></h2><div className="landing-why-copy"><p>A clinical milestone can reshape a company’s outlook. But understanding it means reading beyond the headline: the study design, the funding runway, the remaining development costs, and what the current price implies.</p><p>ValoreaX connects these pieces. It gives you a place to examine the evidence, question the assumptions, and develop your own view.</p></div></div></section>
      <section id="tools" className="landing-tools landing-width" aria-labelledby="tools-title"><div className="landing-section-heading"><div><p className="landing-eyebrow">One connected workspace</p><h2 id="tools-title">Follow the whole thesis.</h2></div><p>From the first question<br />to a view you can explain.</p></div><div className="landing-tool-grid">{tools.map(tool => <article key={tool.number} className="landing-tool"><div className="landing-tool-top"><span className="landing-tool-icon"><Icon name={tool.icon} size="base" /></span><span>{tool.number}</span></div><h3>{tool.title}</h3><p>{tool.text}</p></article>)}</div></section>
      <section id="approach" className="landing-approach landing-width" aria-labelledby="approach-title"><div><p className="landing-eyebrow">A transparent approach</p><h2 id="approach-title">More context.<br /><em>Room for judgment.</em></h2><p>Research is useful when you can see what supports it. ValoreaX keeps evidence, model assumptions, and AI interpretation visible.</p><a className="landing-text-link" href="/?auth=signup">Start exploring <Icon name="arrow_forward" /></a></div><div className="landing-principles">{[
        ["description", "Trace the evidence", "Explore reported financials and clinical records alongside their sources and dates."],
        ["tune", "Inspect the assumptions", "Review model inputs, estimated WACC, and sensitivity analysis. Adjust the discount rate to explore your own view."],
        ["auto_awesome", "Ask better questions", "Use Plutus to synthesize the available evidence. Its interpretation is a starting point for your own review."],
      ].map(([icon, title, text]) => <article key={title}><Icon name={icon} size="base" /><div><h3>{title}</h3><p>{text}</p></div></article>)}</div></section>
      <section className="landing-cta landing-width" aria-labelledby="cta-title"><p className="landing-eyebrow">Make room for a clearer thesis</p><h2 id="cta-title">Your next research question<br /><em>starts here.</em></h2><a className="landing-button" href="/?auth=signup">Create your workspace <Icon name="arrow_forward" /></a><p>Already have an account? <a href="/?auth=login">Sign in</a></p></section>
    </main>
    <footer className="landing-footer landing-width"><div><Brand /><p>Clinical evidence. Company economics. A more informed view.</p></div><div className="landing-footer-note"><p>Educational research, not investment advice.</p><p>Models and AI interpretation involve assumptions and uncertainty.</p><span>© {new Date().getFullYear()} ValoreaX</span></div></footer>
  </div>;
}
