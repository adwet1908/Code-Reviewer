import { useMemo, useState } from "react";
import type { Category, Finding, ReviewResponse, Severity } from "./types";

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low"];
const CATEGORIES: Category[] = ["bug", "edge_case", "security", "performance", "readability"];

const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

const CATEGORY_LABEL: Record<Category, string> = {
  bug: "Bug",
  edge_case: "Edge case",
  security: "Security",
  performance: "Performance",
  readability: "Readability",
};

type Props = {
  response: ReviewResponse;
};

export function Results({ response }: Props) {
  const [severity, setSeverity] = useState<Severity | "all">("all");
  const [category, setCategory] = useState<Category | "all">("all");

  const visible = useMemo(
    () =>
      response.files.map((file) => ({
        filename: file.filename,
        summary: file.review.summary,
        findings: file.review.findings.filter((finding) => {
          if (severity !== "all" && finding.severity !== severity) return false;
          if (category !== "all" && finding.category !== category) return false;
          return true;
        }),
      })),
    [response, severity, category],
  );

  return (
    <section className="results">
      <div className="filters">
        <FilterGroup
          label="Severity"
          value={severity}
          options={[{ id: "all", label: "All" }, ...SEVERITIES.map((id) => ({ id, label: SEVERITY_LABEL[id] }))]}
          onChange={(value) => setSeverity(value as Severity | "all")}
        />
        <FilterGroup
          label="Category"
          value={category}
          options={[{ id: "all", label: "All" }, ...CATEGORIES.map((id) => ({ id, label: CATEGORY_LABEL[id] }))]}
          onChange={(value) => setCategory(value as Category | "all")}
        />
      </div>

      {visible.map((file, index) => (
        <article key={`${file.filename}-${index}`} className="file-review">
          <h2>{file.filename}</h2>
          <p className="summary">{file.summary}</p>
          {file.findings.length === 0 ? (
            <p className="hint">No findings for this filter.</p>
          ) : (
            SEVERITIES.map((level) => {
              const group = file.findings.filter((finding) => finding.severity === level);
              if (group.length === 0) return null;
              return (
                <div key={level} className="group">
                  <h3>{SEVERITY_LABEL[level]}</h3>
                  {group.map((finding, index) => (
                    <FindingCard key={`${level}-${finding.location}-${index}`} finding={finding} />
                  ))}
                </div>
              );
            })
          )}
        </article>
      ))}
    </section>
  );
}

function FindingCard({ finding }: { finding: Finding }) {
  const emphasized = finding.severity === "critical" || finding.severity === "high";
  return (
    <div className={emphasized ? `finding ${finding.severity}` : "finding"}>
      <div className="finding-top">
        <span className={`pill ${finding.severity}`}>{SEVERITY_LABEL[finding.severity]}</span>
        <span className="pill">{CATEGORY_LABEL[finding.category]}</span>
        <span className="location">Line {finding.location}</span>
      </div>
      <p>{finding.issue}</p>
      <p className="suggestion">
        <span>Suggested fix. </span>
        {finding.suggestion}
      </p>
      {finding.evidence && finding.evidence.length > 0 && (
        <p className="hint">
          Evidence: {finding.evidence.map((e) => `${e.path}:${e.start_line}-${e.end_line}`).join(", ")}
        </p>
      )}
    </div>
  );
}

function FilterGroup({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { id: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="filter-group">
      <span>{label}</span>
      <div className="chips">
        {options.map((option) => (
          <button
            key={option.id}
            type="button"
            className={value === option.id ? "chip active" : "chip"}
            onClick={() => onChange(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
