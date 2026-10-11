import type { ModelOption } from "./types";

type Props = {
  models: ModelOption[];
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
};

export function ModelSelect({ models, value, disabled, onChange }: Props) {
  const builtins = models.filter((item) => item.source !== "custom");
  const custom = models.filter((item) => item.source === "custom");
  return (
    <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
      {custom.length === 0
        ? builtins.map((item) => (
            <option key={item.id} value={item.id}>{item.label}</option>
          ))
        : (
          <>
            <optgroup label="Built-in Gemini">
              {builtins.map((item) => (
                <option key={item.id} value={item.id}>{item.label}</option>
              ))}
            </optgroup>
            <optgroup label="Your models">
              {custom.map((item) => (
                <option key={item.id} value={item.id}>{item.label} ({item.provider})</option>
              ))}
            </optgroup>
          </>
        )}
    </select>
  );
}
