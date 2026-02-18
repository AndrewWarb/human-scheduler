"use client";

import type { Task } from "@/lib/types";

interface TaskActionsProps {
  task: Task;
  onAction: (
    taskId: number,
    action: "pause" | "resume" | "complete" | "delete",
  ) => void;
}

export function TaskActions({ task, onAction }: TaskActionsProps) {
  const XNU_ACTION_LABELS: Record<string, string> = {
    pause: "thread_block",
    resume: "thread_wakeup",
    complete: "thread_terminate",
  };

  const actions: {
    label: string;
    action: "pause" | "resume" | "complete";
    className?: string;
  }[] = [];

  if (task.state === "running" || task.state === "runnable") {
    actions.push({ label: "Pause", action: "pause" });
  }
  if (task.state === "waiting") {
    actions.push({ label: "Resume", action: "resume" });
  }
  if (task.state !== "terminated") {
    actions.push({ label: "Complete", action: "complete" });
  }

  if (actions.length === 0) {
    return <span className="text-muted">No actions available</span>;
  }

  return (
    <div className="flex gap-2 flex-wrap">
      {actions.map(({ label, action, className }) => (
        <button
          key={action}
          type="button"
          className={className ?? "btn btn-ghost"}
          onClick={(e) => {
            e.stopPropagation();
            onAction(task.id, action);
          }}
        >
          {label}
          <span className="block text-[0.65rem] opacity-60">{XNU_ACTION_LABELS[action]}</span>
        </button>
      ))}
    </div>
  );
}
