"use client";

import { useApp } from "@/lib/app-context";
import { Card } from "../card";
import { Pill } from "../pill";
import { TaskActions } from "../task-actions";
import { TaskForm } from "../task-form";
import { TaskFilters } from "../task-filters";
import type { Task } from "@/lib/types";

function formatTimestamp(iso: string | null): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function TaskDetail({
  task,
  onAction,
}: {
  task: Task | null;
  onAction: (id: number, action: "pause" | "resume" | "complete") => void;
}) {
  if (!task) {
    return <div className="text-muted italic">Select a task from the list.</div>;
  }

  return (
    <article className="surface-item">
      <h3 className="text-[1.08rem]">{task.title}</h3>
      <div className="flex flex-wrap gap-1.5">
        <Pill>ID: {task.id}</Pill>
        <Pill>{task.life_area_name}</Pill>
        <Pill>{task.urgency_label}</Pill>
        <Pill>State: {task.state}</Pill>
      </div>
      <p className="text-muted">{task.description || "No description"}</p>
      <p className="font-mono text-[0.84rem] text-mono-ink">
        Created: {formatTimestamp(task.created_at)}
      </p>
      <p className="font-mono text-[0.84rem] text-mono-ink">
        Due: {task.due_at ? formatTimestamp(task.due_at) : "--"}
      </p>
      <TaskActions task={task} onAction={onAction} />
    </article>
  );
}

export function TasksView() {
  const {
    state,
    doTaskAction,
    doCreateTask,
    refreshTasks,
    selectTask,
  } = useApp();

  const selected =
    state.tasks.find((t) => t.id === state.selectedTaskId) ??
    state.tasks[0] ??
    null;

  return (
    <div className="animate-[fade-in_0.25s_ease]">
      <div className="grid grid-cols-2 gap-3.5 max-[920px]:grid-cols-1">
        <Card>
          <p className="section-eyebrow">Create Task</p>
          <TaskForm
            settings={state.settings}
            lifeAreas={state.lifeAreas}
            onSubmit={doCreateTask}
          />
        </Card>

        <Card>
          <p className="section-eyebrow">Filters</p>
          <TaskFilters
            settings={state.settings}
            lifeAreas={state.lifeAreas}
            onApply={(f) => refreshTasks(f)}
          />
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-3.5 mt-3.5 max-[920px]:grid-cols-1">
        <Card>
          <p className="section-eyebrow">Task List</p>
          <div className="grid gap-2.5">
            {state.tasks.length === 0 ? (
              <div className="text-muted italic">No tasks found.</div>
            ) : (
              state.tasks.map((task) => (
                <article
                  key={task.id}
                  className={`surface-item surface-item-clickable ${selected?.id === task.id ? "surface-item-active" : ""}`}
                  onClick={() => selectTask(task.id)}
                >
                  <h3 className="text-[1.08rem]">{task.title}</h3>
                  <div className="flex flex-wrap gap-1.5">
                    <Pill>{task.life_area_name}</Pill>
                    <Pill>{task.urgency_label}</Pill>
                    <Pill>{task.state}</Pill>
                  </div>
                  <p className="text-muted">
                    {task.description || "No description"}
                  </p>
                  <TaskActions task={task} onAction={doTaskAction} />
                </article>
              ))
            )}
          </div>
        </Card>

        <Card>
          <p className="section-eyebrow">Task Detail</p>
          <TaskDetail task={selected} onAction={doTaskAction} />
        </Card>
      </div>
    </div>
  );
}
