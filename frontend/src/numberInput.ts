import { formatNumber } from "./format";

/** Strip separators only from well-formed grouped numbers, so 1,00 isn't silently 100. */
export function normalizeNumberInput(text: string): string {
  const trimmed = text.trim();
  if (trimmed.includes(",") && !/^-?\d{1,3}(?:,\d{3})+(?:\.\d*)?$/.test(trimmed)) return trimmed;
  return trimmed.replaceAll(",", "");
}

/** Format the string directly to preserve entered precision and trailing decimal zeros. */
export function formatNumberInput(raw: string): string {
  if (!/^-?\d+(?:\.\d*)?$/.test(raw)) return raw;
  const [integer, decimal] = raw.split(".");
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (decimal === undefined ? "" : `.${decimal}`);
}

export function numberInputError(raw: string, { min, max, step }: { min?: number; max?: number; step?: number | "any" } = {}): string {
  if (!raw) return ""; // Native `required` handles empty fields.
  if (!/^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(raw) || !Number.isFinite(Number(raw))) return "Enter a valid number, such as 1,000 or 1,000.50.";
  const value = Number(raw);
  if (min !== undefined && value < min) return `Enter a number of at least ${formatNumber(min)}.`;
  if (max !== undefined && value > max) return `Enter a number no greater than ${formatNumber(max)}.`;
  if (typeof step === "number" && step > 0) {
    const units = (value - (min ?? 0)) / step;
    if (Math.abs(units - Math.round(units)) > Math.max(1e-7, Math.abs(units) * Number.EPSILON * 8)) return `Use increments of ${step}.`;
  }
  return "";
}
