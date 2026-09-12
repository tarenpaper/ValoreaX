// Shared presentational primitives for the terminal design language.
import type { ReactNode } from "react";

/** A Material Symbols icon. `name` is the ligature (e.g. "search", "biotech"). */
export function Icon({
  name,
  className = "",
  size = "sm",
}: {
  name: string;
  className?: string;
  size?: "sm" | "xs" | "base";
}) {
  const sz = size === "xs" ? "ms-xs" : size === "base" ? "" : "ms-sm";
  return <span className={`material-symbols-outlined ${sz} ${className}`}>{name}</span>;
}

/** Bordered terminal card with a slim uppercase header bar and an optional action. */
export function TerminalPanel({
  title,
  action,
  children,
  className = "",
  bodyClassName = "p-6 pt-2",
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={`terminal-panel border border-outline-variant/50 rounded-3xl flex flex-col overflow-hidden ${className}`}
    >
      {title && (
        <header className="min-h-16 shrink-0 px-6 py-4 flex justify-between gap-3 items-center">
          <span className="font-headline-panel text-headline-panel text-on-surface normal-case">{title}</span>
          {action}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

/** Legacy generic panel (used by the Backtest view). */
export function Panel({
  title,
  right,
  children,
  className = "",
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`terminal-panel rounded-3xl border border-outline-variant/50 ${className}`}>
      {title && (
        <header className="flex items-center justify-between px-6 pt-6 pb-3">
          <h2 className="font-headline-panel text-headline-panel text-on-surface">{title}</h2>
          {right}
        </header>
      )}
      <div className="p-6 pt-2">{children}</div>
    </section>
  );
}

export function Badge({
  children,
  className = "",
  title,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 font-data-sm text-[9px] font-medium uppercase tracking-wide ${className}`}
    >
      {children}
    </span>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-sm border border-outline-variant bg-surface px-3 py-2">
      <div className="font-label-caps text-label-caps uppercase text-on-surface-variant">{label}</div>
      <div className="mt-0.5 font-data-tabular text-[14px] leading-tight text-on-surface">{value}</div>
      {sub && <div className="mt-1">{sub}</div>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 font-body-main text-body-main text-on-surface-variant">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-outline-variant border-t-primary" />
      {label ?? "Loading…"}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-sm border border-error/40 bg-error/10 px-3 py-2 font-body-main text-body-main text-error">
      {message}
    </div>
  );
}
