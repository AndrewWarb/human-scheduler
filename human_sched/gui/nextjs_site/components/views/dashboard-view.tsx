"use client";

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

function ThreadRow({
  thread,
  onAction,
}: {
  thread: SchedulerThread;
  onAction: (taskId: number, action: "pause" | "complete") => void;
}) {
  const canAct = thread.state === "running" || thread.state === "runnable";

  return (
    <div
      className={`surface-item grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 py-2.5 px-3${
        thread.is_active ? " surface-item-active" : ""
      }`}
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

      <div className="col-span-2 flex flex-wrap items-center gap-x-4 gap-y-0.5 text-[0.72rem] text-muted font-mono">
        <span>pri {thread.sched_pri}</span>
        <span>cpu {thread.cpu_usage}</span>
        <span>{thread.urgency_label}</span>
        <span>{thread.life_area}</span>
        <span>ctx {thread.context_switches}</span>
        {canAct && (
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
  const { state, doTaskAction } = useApp();
  const ss = state.schedulerState;

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
    if (a.is_active && !b.is_active) return -1;
    if (!a.is_active && b.is_active) return 1;
    return b.sched_pri - a.sched_pri;
  });

  return (
    <div className="animate-[fade-in_0.25s_ease] grid gap-3.5">
      {/* Top row: tick + quantum */}
      <div className="grid grid-cols-3 gap-3.5 max-[640px]:grid-cols-1">
        <Card>
          <p className="section-eyebrow">Scheduler Tick</p>
          <p className="font-mono text-[1.4rem] tracking-wider">{ss.tick}</p>
        </Card>
        <Card>
          <p className="section-eyebrow">Threads</p>
          <p className="font-mono text-[1.4rem] tracking-wider">
            {activeThreads.length}
            <span className="text-[0.76rem] text-muted ml-1">active</span>
          </p>
        </Card>
        <Card>
          <p className="section-eyebrow">Quantum Remaining</p>
          <p className="font-mono text-[1.4rem] tracking-wider">
            {ss.quantum_remaining_us > 0
              ? `${(ss.quantum_remaining_us / 1_000_000).toFixed(1)}s`
              : "--"}
          </p>
        </Card>
      </div>

      {/* Run queue */}
      <Card>
        <p className="section-eyebrow">Run Queue</p>
        <div className="grid gap-1.5">
          {sortedThreads.length > 0 ? (
            sortedThreads.map((t) => (
              <ThreadRow key={t.task_id} thread={t} onAction={doTaskAction} />
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
          <div className="font-mono text-[0.72rem] text-mono-ink leading-relaxed max-h-48 overflow-y-auto">
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
