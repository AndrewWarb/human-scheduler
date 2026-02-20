"use client";

import { useState } from "react";
import { useApp } from "@/lib/app-context";
import { Card } from "../card";
import type { SchedulerThread, SchedulerLifeArea } from "@/lib/types";

const STATE_COLORS: Record<string, string> = {
  running: "bg-emerald-400",
  runnable: "bg-sky-400",
  waiting: "bg-amber-400",
  terminated: "bg-zinc-500",
};

const STATE_LABELS: Record<string, string> = {
  running: "Running",
  runnable: "Runnable",
  waiting: "Blocked",
  terminated: "Terminated",
};

const STATE_SORT_ORDER: Record<string, number> = {
  running: 0,
  runnable: 1,
  waiting: 2,
  terminated: 3,
};

function formatQuantumUs(us: number): string {
  const totalSeconds = Math.max(0, Math.round(us));
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const minutes = totalMinutes % 60;
  const totalHours = Math.floor(totalMinutes / 60);
  const hours = totalHours % 24;
  const days = Math.floor(totalHours / 24);

  if (days > 0) return `${days}d ${hours}h ${minutes}m ${seconds}s`;
  if (totalHours > 0) return `${totalHours}h ${minutes}m ${seconds}s`;
  if (totalMinutes > 0) return `${totalMinutes}m ${seconds}s`;
  return `${seconds}s`;
}

function StatChip({
  label,
  value,
  className = "",
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border border-white/[0.16] bg-white/[0.04] px-2 py-0.5 text-[0.67rem] text-mono-ink font-mono ${className}`}
    >
      <span className="uppercase tracking-[0.08em] text-[0.58rem] text-muted">
        {label}
      </span>
      <span className="max-w-[15rem] truncate">{value}</span>
    </span>
  );
}

function ThreadRow({
  thread,
  onAction,
  onUrgencyChange,
  urgencyOptions,
  warpBudget,
  edfDeadline,
  activeTooltipId,
  setActiveTooltipId,
}: {
  thread: SchedulerThread;
  onAction: (taskId: number, action: "pause" | "resume" | "complete") => void;
  onUrgencyChange: (taskId: number, urgencyTier: string) => void;
  urgencyOptions: Array<{ value: string; label: string }>;
  warpBudget: { remaining_hours: number; total_hours: number } | null;
  edfDeadline: { deadline_remaining_hours: number; deadline_at: string | null } | null;
  activeTooltipId: string | null;
  setActiveTooltipId: (tooltipId: string | null) => void;
}) {
  const isRunnable = thread.state === "running" || thread.state === "runnable";
  const isBlocked = thread.state === "waiting";
  const tierOptions =
    urgencyOptions.length > 0
      ? urgencyOptions
      : [{ value: thread.urgency_tier, label: thread.urgency_label }];
  const quantumTooltipId = `quantum-tooltip-thread-${thread.task_id}`;
  const quantumTooltipActive = activeTooltipId === quantumTooltipId;

  return (
    <div
      className={`surface-item grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 py-2.5 px-3${
        thread.is_active ? " surface-item-active" : ""
      }${thread.state === "waiting" ? " opacity-50" : ""}`}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={`inline-block w-2 h-2 rounded-full shrink-0 ${
            STATE_COLORS[thread.state] ?? "bg-zinc-600"
          }`}
        />
        <span className="truncate font-medium text-[0.88rem]">
          {thread.title}
        </span>
      </div>
      <span className="text-[0.72rem] text-muted whitespace-nowrap">
        {STATE_LABELS[thread.state] ?? thread.state}
      </span>

      <div className="col-span-2 grid gap-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <StatChip label="pri" value={String(thread.sched_pri)} />
          <StatChip
            label="cpu used"
            value={formatQuantumUs(thread.cpu_usage_hours * 3600)}
          />
          <span
            className="relative inline-flex items-center gap-1 rounded-full border border-white/[0.16] bg-white/[0.04] px-2 py-0.5 text-[0.67rem] text-mono-ink font-mono cursor-help"
            tabIndex={0}
            aria-describedby={quantumTooltipActive ? quantumTooltipId : undefined}
            onMouseEnter={() => setActiveTooltipId(quantumTooltipId)}
            onMouseLeave={() => setActiveTooltipId(null)}
            onFocus={() => setActiveTooltipId(quantumTooltipId)}
            onBlur={() => setActiveTooltipId(null)}
          >
            <span className="uppercase tracking-[0.08em] text-[0.58rem] text-muted">
              q
            </span>
            <span>
              {formatQuantumUs(thread.quantum_remaining_hours * 3600)} /{" "}
              {formatQuantumUs(thread.quantum_base_hours * 3600)}
            </span>
            {quantumTooltipActive && (
              <span
                className="interactivity-chip-tooltip"
                role="tooltip"
                id={quantumTooltipId}
              >
                <span className="interactivity-chip-tooltip-title">
                  Quantum A / B
                </span>
                <span>A = remaining slice time for this thread.</span>
                <span>B = full slice budget for this thread&apos;s bucket.</span>
                <span>At 0, the scheduler re-evaluates.</span>
              </span>
            )}
          </span>
          <StatChip
            label="warp"
            value={
              warpBudget && warpBudget.total_hours > 0
                ? `${formatQuantumUs(warpBudget.remaining_hours * 3600)} / ${formatQuantumUs(warpBudget.total_hours * 3600)}`
                : "--"
            }
          />
          <StatChip
            label="edf"
            value={
              edfDeadline && edfDeadline.deadline_at
                ? formatQuantumUs(edfDeadline.deadline_remaining_hours * 3600)
                : "--"
            }
          />
          <StatChip label="bucket" value={thread.sched_bucket} />
          <StatChip label="ctx" value={String(thread.context_switches)} />
          <StatChip label="area" value={thread.life_area} />
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <label className="inline-flex items-center gap-1.5 text-[0.68rem]">
            <span className="uppercase tracking-[0.08em] text-[0.58rem] text-muted">
              urgency
            </span>
            <select
              className="field-control !py-0 !px-1.5 !h-6 !text-[0.68rem] !rounded-md !min-w-[8.8rem]"
              value={thread.urgency_tier}
              onChange={(event) => {
                const nextTier = event.target.value;
                if (nextTier !== thread.urgency_tier) {
                  onUrgencyChange(thread.task_id, nextTier);
                }
              }}
              aria-label={`Set urgency for ${thread.title}`}
            >
              {tierOptions.map((tier) => (
                <option key={tier.value} value={tier.value}>
                  {tier.label}
                </option>
              ))}
            </select>
          </label>
          {isRunnable && (
            <>
              <button
                className="btn btn-ghost !py-0.5 !px-2 !text-[0.68rem] !rounded-lg"
                onClick={() => onAction(thread.task_id, "pause")}
              >
                Block
              </button>
              <button
                className="btn btn-ghost !py-0.5 !px-2 !text-[0.68rem] !rounded-lg"
                onClick={() => onAction(thread.task_id, "complete")}
              >
                Terminate
              </button>
            </>
          )}
          {isBlocked && (
            <>
              <button
                className="btn btn-ghost !py-0.5 !px-2 !text-[0.68rem] !rounded-lg"
                onClick={() => onAction(thread.task_id, "resume")}
              >
                Unblock
              </button>
              <button
                className="btn btn-ghost !py-0.5 !px-2 !text-[0.68rem] !rounded-lg"
                onClick={() => onAction(thread.task_id, "complete")}
              >
                Terminate
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function InteractivityBar({
  area,
}: {
  area: SchedulerLifeArea;
}) {
  const scores = Object.entries(area.interactivity_scores);
  if (scores.length === 0) return null;

  return (
    <div className="surface-item py-2.5 px-3">
      <div className="flex items-baseline gap-2 mb-1.5">
        <span className="font-medium text-[0.88rem]">{area.name}</span>
        <span className="text-[0.68rem] text-muted">
          {area.task_count} {area.task_count === 1 ? "task" : "tasks"}
        </span>
      </div>
      <div className="flex gap-1.5">
        {scores.map(([bucket, score]) => (
          <div key={bucket} className="flex-1 min-w-0">
            <div className="flex justify-between text-[0.62rem] text-muted mb-0.5 font-mono">
              <span>{bucket}</span>
              <span>{score}</span>
            </div>
            <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${Math.max(2, Math.min(100, (score / 20) * 100))}%`,
                  background:
                    score <= 5
                      ? "rgba(52, 211, 153, 0.7)"
                      : score <= 12
                        ? "rgba(251, 191, 36, 0.7)"
                        : "rgba(248, 113, 113, 0.7)",
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function DashboardView() {
  const { state, doTaskAction, doChangeTaskUrgency } = useApp();
  const [activeTooltipId, setActiveTooltipId] = useState<string | null>(null);
  const ss = state.schedulerState;
  const urgencyOptions = state.settings?.urgency_tiers ?? [];
  const topQuantumLabelTooltipId = "quantum-tooltip-kpi-label";
  const topQuantumLabelTooltipActive = activeTooltipId === topQuantumLabelTooltipId;
  const topQuantumValueTooltipId = "quantum-tooltip-kpi-value";
  const topQuantumValueTooltipActive = activeTooltipId === topQuantumValueTooltipId;
  const topWarpTooltipId = "warp-tooltip-kpi";
  const topWarpTooltipActive = activeTooltipId === topWarpTooltipId;
  const topEdfTooltipId = "edf-tooltip-kpi";
  const topEdfTooltipActive = activeTooltipId === topEdfTooltipId;

  if (!ss) {
    return (
      <div className="animate-[fade-in_0.25s_ease]">
        <p className="text-muted text-center py-8">
          {state.simulationRunning
            ? "Loading scheduler state..."
            : "Start the simulation to begin scheduling."}
        </p>
      </div>
    );
  }

  const activeThreads = ss.threads.filter((t) => t.state !== "terminated");
  const sortedThreads = [...activeThreads].sort((a, b) => {
    const aRank = a.run_queue_rank ?? Number.MAX_SAFE_INTEGER;
    const bRank = b.run_queue_rank ?? Number.MAX_SAFE_INTEGER;
    if (aRank !== bRank) return aRank - bRank;

    const aStateOrder = STATE_SORT_ORDER[a.state] ?? Number.MAX_SAFE_INTEGER;
    const bStateOrder = STATE_SORT_ORDER[b.state] ?? Number.MAX_SAFE_INTEGER;
    if (aStateOrder !== bStateOrder) return aStateOrder - bStateOrder;

    if (a.is_active && !b.is_active) return -1;
    if (!a.is_active && b.is_active) return 1;
    if (a.sched_pri !== b.sched_pri) return b.sched_pri - a.sched_pri;
    return a.task_id - b.task_id;
  });
  const warpByBucket = new Map(
    (ss.warp_budgets ?? []).map((budget) => [budget.bucket, budget]),
  );
  const edfByBucket = new Map(
    (ss.edf_deadlines ?? []).map((deadline) => [deadline.bucket, deadline]),
  );
  const kpiCardClass = "h-40 min-w-0 flex flex-col justify-between";
  const kpiValueClass =
    "font-mono text-[clamp(1rem,1.4vw,1.4rem)] leading-tight tracking-wider break-words";

  return (
    <div className="animate-[fade-in_0.25s_ease] grid gap-3.5">
      {/* Top row: tick + quantum */}
      <div className="grid grid-cols-5 gap-3.5 max-[640px]:grid-cols-1">
        <Card className={kpiCardClass}>
          <p className="section-eyebrow">Scheduler Time</p>
          <p className={kpiValueClass}>
            {formatQuantumUs(ss.now_hours * 3600)}
          </p>
          <p className="text-[0.68rem] text-muted font-mono leading-tight break-words">
            tick {ss.tick.toLocaleString()}
          </p>
        </Card>
        <Card className={kpiCardClass}>
          <p className="section-eyebrow">Threads</p>
          <p className={kpiValueClass}>
            {activeThreads.length}
            <span className="text-[0.76rem] text-muted ml-1">active</span>
          </p>
        </Card>
        <Card className={kpiCardClass}>
          <p
            className="section-eyebrow relative inline-block cursor-help"
            tabIndex={0}
            aria-describedby={topQuantumLabelTooltipActive ? topQuantumLabelTooltipId : undefined}
            onMouseEnter={() => setActiveTooltipId(topQuantumLabelTooltipId)}
            onMouseLeave={() =>
              setActiveTooltipId((current) => (current === topQuantumLabelTooltipId ? null : current))
            }
            onFocus={() => setActiveTooltipId(topQuantumLabelTooltipId)}
            onBlur={() =>
              setActiveTooltipId((current) => (current === topQuantumLabelTooltipId ? null : current))
            }
          >
            Quantum
            {topQuantumLabelTooltipActive && (
              <span className="interactivity-chip-tooltip" role="tooltip" id={topQuantumLabelTooltipId}>
                <span className="interactivity-chip-tooltip-title">Quantum A / B</span>
                <span>A = remaining slice time for the running task.</span>
                <span>B = full slice budget for that task's bucket.</span>
                <span>At 0, the scheduler re-evaluates.</span>
              </span>
            )}
          </p>
          <p
            className={`${kpiValueClass} relative block cursor-help`}
            tabIndex={0}
            aria-describedby={topQuantumValueTooltipActive ? topQuantumValueTooltipId : undefined}
            onMouseEnter={() => setActiveTooltipId(topQuantumValueTooltipId)}
            onMouseLeave={() =>
              setActiveTooltipId((current) => (current === topQuantumValueTooltipId ? null : current))
            }
            onFocus={() => setActiveTooltipId(topQuantumValueTooltipId)}
            onBlur={() =>
              setActiveTooltipId((current) => (current === topQuantumValueTooltipId ? null : current))
            }
          >
            {ss.quantum_total_hours > 0
              ? `${formatQuantumUs(ss.quantum_remaining_hours * 3600)} / ${formatQuantumUs(ss.quantum_total_hours * 3600)}`
              : "--"}
            {topQuantumValueTooltipActive && (
              <span className="interactivity-chip-tooltip" role="tooltip" id={topQuantumValueTooltipId}>
                <span className="interactivity-chip-tooltip-title">Quantum A / B</span>
                <span>A = remaining slice time for the running task.</span>
                <span>B = full slice budget for that task's bucket.</span>
                <span>At 0, the scheduler re-evaluates.</span>
              </span>
            )}
          </p>
        </Card>
        <Card className={kpiCardClass}>
          <p
            className="section-eyebrow relative inline-block cursor-help"
            tabIndex={0}
            aria-describedby={topWarpTooltipActive ? topWarpTooltipId : undefined}
            onMouseEnter={() => setActiveTooltipId(topWarpTooltipId)}
            onMouseLeave={() =>
              setActiveTooltipId((current) => (current === topWarpTooltipId ? null : current))
            }
            onFocus={() => setActiveTooltipId(topWarpTooltipId)}
            onBlur={() =>
              setActiveTooltipId((current) => (current === topWarpTooltipId ? null : current))
            }
          >
            Warp Budget
            {topWarpTooltipActive && (
              <span className="interactivity-chip-tooltip" role="tooltip" id={topWarpTooltipId}>
                <span className="interactivity-chip-tooltip-title">Warp A / B</span>
                <span>A = remaining warp budget for the active root bucket.</span>
                <span>B = full warp budget for that bucket.</span>
                <span>Warp lets higher buckets jump ahead temporarily.</span>
              </span>
            )}
          </p>
          <p className={kpiValueClass}>
            {ss.warp_budget_total_hours > 0
              ? `${formatQuantumUs(ss.warp_budget_remaining_hours * 3600)} / ${formatQuantumUs(ss.warp_budget_total_hours * 3600)}`
              : "--"}
          </p>
          <p className="text-[0.68rem] text-muted font-mono leading-tight break-words">
            {ss.warp_budget_bucket != null ? `bucket ${ss.warp_budget_bucket}` : "--"}
          </p>
        </Card>
        <Card className={kpiCardClass}>
          <p
            className="section-eyebrow relative inline-block cursor-help"
            tabIndex={0}
            aria-describedby={topEdfTooltipActive ? topEdfTooltipId : undefined}
            onMouseEnter={() => setActiveTooltipId(topEdfTooltipId)}
            onMouseLeave={() =>
              setActiveTooltipId((current) => (current === topEdfTooltipId ? null : current))
            }
            onFocus={() => setActiveTooltipId(topEdfTooltipId)}
            onBlur={() =>
              setActiveTooltipId((current) => (current === topEdfTooltipId ? null : current))
            }
          >
            EDF Deadline
            {topEdfTooltipActive && (
              <span className="interactivity-chip-tooltip" role="tooltip" id={topEdfTooltipId}>
                <span className="interactivity-chip-tooltip-title">EDF deadline</span>
                <span>Earliest-deadline target for the active root bucket.</span>
                <span>Shown as time remaining until that deadline.</span>
              </span>
            )}
          </p>
          <p className={kpiValueClass}>
            {ss.edf_deadline_at
              ? formatQuantumUs(ss.edf_deadline_remaining_hours * 3600)
              : "--"}
          </p>
          <p className="text-[0.68rem] text-muted font-mono leading-tight break-words">
            {ss.edf_deadline_bucket != null ? `bucket ${ss.edf_deadline_bucket}` : "--"}
          </p>
        </Card>
      </div>

      {/* Run queue */}
      <Card>
        <p className="section-eyebrow">Run Queue</p>
        <div className="grid gap-1.5">
          {sortedThreads.length > 0 ? (
            sortedThreads.map((t) => (
              <ThreadRow
                key={t.task_id}
                thread={t}
                onAction={doTaskAction}
                onUrgencyChange={doChangeTaskUrgency}
                urgencyOptions={urgencyOptions}
                warpBudget={warpByBucket.get(t.sched_bucket) ?? null}
                edfDeadline={edfByBucket.get(t.sched_bucket) ?? null}
                activeTooltipId={activeTooltipId}
                setActiveTooltipId={setActiveTooltipId}
              />
            ))
          ) : (
            <p className="text-muted text-[0.85rem] py-2">No active threads.</p>
          )}
        </div>
      </Card>

      {/* Interactivity scores by life area */}
      {ss.life_areas.length > 0 && (
        <Card>
          <p className="section-eyebrow">Interactivity Scores</p>
          <div className="grid gap-1.5">
            {ss.life_areas.map((area) => (
              <InteractivityBar key={area.id} area={area} />
            ))}
          </div>
        </Card>
      )}

      {/* Recent trace log */}
      {ss.recent_trace.length > 0 && (
        <Card>
          <p className="section-eyebrow">Recent Scheduler Trace</p>
          <div className="font-mono text-[0.72rem] text-mono-ink leading-relaxed max-h-[36rem] overflow-y-auto">
            {ss.recent_trace.map((line, i) => (
              <div key={i} className="py-0.5 border-b border-white/[0.04] last:border-0">
                {line}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
