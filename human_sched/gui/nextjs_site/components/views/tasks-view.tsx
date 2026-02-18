"use client";

import { useApp } from "@/lib/app-context";
import { Card } from "../card";
import { Pill } from "../pill";
import { TaskActions } from "../task-actions";
import { TaskForm } from "../task-form";
import type { Task } from "@/lib/types";

function formatTimestamp(iso: string | null): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function TaskItem({
  task,
  isActive,
  onAction,
}: {
  task: Task;
  isActive: boolean;
  onAction: (id: number, action: "pause" | "resume" | "complete") => void;
}) {
  return (
    <article className={`surface-item task-item-compact ${isActive ? "surface-item-active" : ""}`}>
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-[1rem]">{task.title}</h3>
        <button
          type="button"
          className="icon-btn icon-btn-danger"
          aria-label={`Delete task ${task.title}`}
          title="Delete task"
          onClick={() => {
            if (!window.confirm(`Delete task "${task.title}"?`)) return;
            onAction(task.id, "delete");
          }}
        >
          ×
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Pill>ID: {task.id}</Pill>
        <Pill>{task.urgency_label}</Pill>
        <Pill>State: {task.state}</Pill>
      </div>
      <p className="font-mono text-[0.8rem] text-mono-ink">
        Created: {formatTimestamp(task.created_at)} • Due: {task.due_at ? formatTimestamp(task.due_at) : "--"}
      </p>
      <TaskActions task={task} onAction={onAction} />
    </article>
  );
}

export function TasksView() {
  const { state, doTaskAction, doCreateTask } = useApp();

  const tasksByLifeArea = new Map<number, Task[]>();
  for (const area of state.lifeAreas) {
    tasksByLifeArea.set(area.id, []);
  }

  const orphanTasks: Task[] = [];
  for (const task of state.tasks) {
    const bucket = tasksByLifeArea.get(task.life_area_id);
    if (bucket) {
      bucket.push(task);
    } else {
      orphanTasks.push(task);
    }
  }

  return (
    <div className="animate-[fade-in_0.25s_ease]">
      <div className="grid grid-cols-1 gap-3.5">
        <Card className="tasks-create-card">
          <p className="section-eyebrow">Create Task</p>
          <TaskForm
            settings={state.settings}
            lifeAreas={state.lifeAreas}
            onSubmit={doCreateTask}
          />
        </Card>
      </div>

      <div className="grid grid-cols-2 max-[1080px]:grid-cols-1 gap-3.5 mt-3.5">
        {state.lifeAreas.length === 0 ? (
          <Card className="tasks-area-card">
            <p className="section-eyebrow">Tasks</p>
            <div className="text-muted italic">
              Create a life area first, then add tasks.
            </div>
          </Card>
        ) : (
          state.lifeAreas.map((area) => {
            const areaTasks = tasksByLifeArea.get(area.id) ?? [];

            return (
              <Card key={area.id} className="tasks-area-card">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="section-eyebrow">Life Area</p>
                    <h3 className="text-[1.08rem]">{area.name}</h3>
                  </div>
                  <Pill>Tasks: {areaTasks.length}</Pill>
                </div>

                <div className="grid gap-2.5">
                  {areaTasks.length === 0 ? (
                    <div className="text-muted italic">
                      No tasks in this life area.
                    </div>
                  ) : (
                    areaTasks.map((task) => (
                      <TaskItem
                        key={task.id}
                        task={task}
                        isActive={state.dispatch?.task.id === task.id}
                        onAction={doTaskAction}
                      />
                    ))
                  )}
                </div>
              </Card>
            );
          })
        )}

        {orphanTasks.length > 0 && (
          <Card className="tasks-area-card">
            <div className="flex items-center justify-between gap-2">
              <div>
                <p className="section-eyebrow">Unassigned</p>
                <h3 className="text-[1.08rem]">Orphaned Tasks</h3>
              </div>
              <Pill>Tasks: {orphanTasks.length}</Pill>
            </div>
            <div className="grid gap-2.5">
              {orphanTasks.map((task) => (
                <TaskItem
                  key={task.id}
                  task={task}
                  isActive={state.dispatch?.task.id === task.id}
                  onAction={doTaskAction}
                />
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
