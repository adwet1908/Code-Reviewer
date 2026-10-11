export type AgentStepStatus = "pending" | "running" | "done" | "error";

export type AgentStep = {
  id: string;
  label: string;
  status: AgentStepStatus;
  detail?: string | null;
};

const DEFAULT_STEPS: AgentStep[] = [
  { id: "analyser", label: "Analyser", status: "pending" },
  { id: "retriever", label: "Retriever", status: "pending" },
  { id: "reviewer", label: "Reviewer", status: "pending" },
  { id: "critic", label: "Critic", status: "pending" },
  { id: "reporter", label: "Reporter", status: "pending" },
];

type Props = {
  steps: AgentStep[];
  active: string | null;
};

export function emptyAgentSteps(): AgentStep[] {
  return DEFAULT_STEPS.map((step) => ({ ...step }));
}

export function applyAgentEvent(
  steps: AgentStep[],
  agent: string,
  status: string,
  detail?: string | null,
): AgentStep[] {
  const mapped: AgentStepStatus =
    status === "running" ? "running" : status === "error" ? "error" : status === "done" ? "done" : "pending";
  return steps.map((step) => {
    if (step.id !== agent) {
      // Only one agent running at a time — demote previous running to done if needed.
      if (mapped === "running" && step.status === "running") {
        return { ...step, status: "done" };
      }
      return step;
    }
    return { ...step, status: mapped, detail: detail ?? step.detail };
  });
}

export function AgentProgress({ steps, active }: Props) {
  return (
    <section className="panel agent-progress" aria-live="polite">
      <h2>Agent pipeline</h2>
      <p className="hint">
        {active ? <>Running now: <strong>{labelFor(active, steps)}</strong></> : "Waiting for agents…"}
      </p>
      <ol className="agent-steps">
        {steps.map((step) => (
          <li key={step.id} className={`agent-step agent-${step.status}${active === step.id ? " agent-active" : ""}`}>
            <span className="agent-dot" aria-hidden />
            <div>
              <strong>{step.label}</strong>
              <span className="meta">
                {statusLabel(step.status)}
                {step.detail ? ` · ${step.detail}` : ""}
              </span>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function labelFor(id: string, steps: AgentStep[]): string {
  return steps.find((step) => step.id === id)?.label ?? id;
}

function statusLabel(status: AgentStepStatus): string {
  if (status === "running") return "running now";
  if (status === "done") return "done";
  if (status === "error") return "error";
  return "waiting";
}
