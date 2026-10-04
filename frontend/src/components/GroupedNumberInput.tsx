import { useEffect, useRef, useState, type InputHTMLAttributes } from "react";
import { formatNumberInput, normalizeNumberInput, numberInputError } from "../numberInput";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "onChange" | "min" | "max" | "step"> & {
  value: string;
  onChange: (value: string) => void;
  min?: number;
  max?: number;
  step?: number | "any";
};

/** Show grouped amounts at rest, and an unformatted draft while editing to keep the cursor stable. */
export default function GroupedNumberInput({ value, onChange, min, max, step, onFocus, onBlur, ...props }: Props) {
  const [editing, setEditing] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const error = numberInputError(value, { min, max, step });
  useEffect(() => { input.current?.setCustomValidity(error); }, [error]);
  return <input {...props} ref={input} type="text" inputMode="decimal" aria-invalid={error ? true : undefined}
    value={editing ? value : formatNumberInput(value)}
    onFocus={event => { setEditing(true); onFocus?.(event); }}
    onBlur={event => { setEditing(false); onBlur?.(event); }}
    onChange={event => {
      const raw = normalizeNumberInput(event.target.value);
      event.target.setCustomValidity(numberInputError(raw, { min, max, step }));
      onChange(raw);
    }} />;
}
