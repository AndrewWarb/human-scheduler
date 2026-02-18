"use client";

import { useState } from "react";
import { useApp } from "@/lib/app-context";
import type { LifeArea } from "@/lib/types";
import { Card } from "../card";
import { Pill } from "../pill";
import { LifeAreaForm } from "../life-area-form";

export function LifeAreasView() {
  const { state, doCreateLifeArea, doDeleteLifeArea, doRenameLifeArea, showToast } =
    useApp();
  const [renamingLifeAreaId, setRenamingLifeAreaId] = useState<number | null>(
    null,
  );
  const [deletingLifeAreaId, setDeletingLifeAreaId] = useState<number | null>(
    null,
  );

  async function handleRenameLifeArea(area: LifeArea) {
    const raw = window.prompt("Edit life area name:", area.name);
    if (raw == null) return;

    const nextName = raw.trim();
    if (!nextName || nextName === area.name) {
      if (!nextName) showToast("Life area name is required.");
      return;
    }

    setRenamingLifeAreaId(area.id);
    try {
      await doRenameLifeArea(area.id, nextName);
    } finally {
      setRenamingLifeAreaId((current) => (current === area.id ? null : current));
    }
  }

  async function handleDeleteLifeArea(area: LifeArea) {
    const taskWord = area.task_count === 1 ? "task" : "tasks";
    const confirmed = window.confirm(
      `Delete life area "${area.name}"? This will also delete ${area.task_count} ${taskWord}.`,
    );
    if (!confirmed) return;

    setDeletingLifeAreaId(area.id);
    try {
      await doDeleteLifeArea(area.id);
    } finally {
      setDeletingLifeAreaId((current) => (current === area.id ? null : current));
    }
  }

  return (
    <div className="animate-[fade-in_0.25s_ease]">
      <div className="grid grid-cols-2 gap-3.5 max-[920px]:grid-cols-1">
        <Card>
          <p className="section-eyebrow">Create Life Area</p>
          <LifeAreaForm onSubmit={doCreateLifeArea} />
        </Card>

        <Card>
          <p className="section-eyebrow">Life Areas</p>
          <div className="grid gap-2.5">
            {state.lifeAreas.length === 0 ? (
              <div className="text-muted italic">No life areas yet.</div>
            ) : (
              state.lifeAreas.map((area) => {
                const scoreText = Object.entries(
                  area.interactivity_scores ?? {},
                )
                  .map(([bucket, score]) => `${bucket}:${score}`)
                  .join(" | ");

                return (
                  <article
                    key={area.id}
                    className="surface-item"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="text-[1.08rem]">{area.name}</h3>
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          className="icon-btn"
                          disabled={
                            renamingLifeAreaId === area.id ||
                            deletingLifeAreaId === area.id
                          }
                          aria-label={`Rename life area ${area.name}`}
                          onClick={() => void handleRenameLifeArea(area)}
                        >
                          {renamingLifeAreaId === area.id ? "…" : "✎"}
                        </button>
                        <button
                          type="button"
                          className="icon-btn icon-btn-danger"
                          disabled={
                            renamingLifeAreaId === area.id ||
                            deletingLifeAreaId === area.id
                          }
                          aria-label={`Delete life area ${area.name}`}
                          onClick={() => void handleDeleteLifeArea(area)}
                        >
                          {deletingLifeAreaId === area.id ? "…" : "×"}
                        </button>
                      </div>
                    </div>
                    <p className="text-muted">
                      {area.description || "No description"}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      <Pill>ID: {area.id}</Pill>
                      <Pill>Tasks: {area.task_count}</Pill>
                    </div>
                    <p className="font-mono text-[0.84rem] text-mono-ink">
                      Interactivity: {scoreText || "--"}
                    </p>
                  </article>
                );
              })
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
