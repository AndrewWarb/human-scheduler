"use client";

import { useState } from "react";
import { useApp } from "@/lib/app-context";
import type { LifeArea } from "@/lib/types";
import { Card } from "../card";
import { Pill } from "../pill";
import { LifeAreaForm } from "../life-area-form";

const INTERACTIVITY_BUCKETS: Array<{
  key: string;
  label: string;
  xnuName: string;
  description: string;
}> = [
  {
    key: "FIXPRI",
    label: "Fixed",
    xnuName: "TH_BUCKET_FIXPRI",
    description:
      "Fixed-priority (above-UI) work. Strict priority behavior, outside normal timeshare buckets.",
  },
  {
    key: "FG",
    label: "Foreground",
    xnuName: "TH_BUCKET_SHARE_FG",
    description:
      "Foreground timeshare work for active, user-visible interactions that should feel responsive.",
  },
  {
    key: "IN",
    label: "Interactive",
    xnuName: "TH_BUCKET_SHARE_IN",
    description:
      "User-initiated timeshare work started by direct user action and expected to complete soon.",
  },
  {
    key: "DF",
    label: "Deferred",
    xnuName: "TH_BUCKET_SHARE_DF",
    description:
      "Default timeshare work for normal tasks without explicit urgency boosts or heavy deferral.",
  },
  {
    key: "UT",
    label: "Utility",
    xnuName: "TH_BUCKET_SHARE_UT",
    description:
      "Utility timeshare work that can progress with less urgency than interactive/foreground tasks.",
  },
  {
    key: "BG",
    label: "Background",
    xnuName: "TH_BUCKET_SHARE_BG",
    description:
      "Background timeshare work with the lowest responsiveness priority and highest tolerance for delay.",
  },
];

export function LifeAreasView() {
  const { state, doCreateLifeArea, doDeleteLifeArea, doRenameLifeArea, showToast } =
    useApp();
  const [renamingLifeAreaId, setRenamingLifeAreaId] = useState<number | null>(
    null,
  );
  const [deletingLifeAreaId, setDeletingLifeAreaId] = useState<number | null>(
    null,
  );
  const [activeTooltipId, setActiveTooltipId] = useState<string | null>(null);

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
      <div className="grid items-start grid-cols-1 gap-3.5">
        <Card>
          <p className="section-eyebrow">Create Life Area</p>
          <LifeAreaForm onSubmit={doCreateLifeArea} />
        </Card>
      </div>

      <div className="grid items-start grid-cols-2 gap-3.5 mt-3.5 max-[920px]:grid-cols-1">
        {state.lifeAreas.length === 0 ? (
          <div className="text-muted italic">No life areas yet.</div>
        ) : (
          state.lifeAreas.map((area) => {
                const interactivityScores = area.interactivity_scores ?? {};
                const knownKeys = new Set(
                  INTERACTIVITY_BUCKETS.map(({ key }) => key),
                );
                const labeledScores = INTERACTIVITY_BUCKETS
                  .filter(({ key }) => key in interactivityScores)
                  .map(({ key, label, xnuName, description }) => ({
                    key,
                    label,
                    xnuName,
                    description,
                    score: interactivityScores[key],
                  }));
                const extraScores = Object.entries(interactivityScores)
                  .filter(([key]) => !knownKeys.has(key))
                  .map(([key, score]) => ({
                    key,
                    label: key,
                    xnuName: key,
                    description: "Custom bucket score exposed by the scheduler adapter.",
                    score,
                  }));
                const allScores = [...labeledScores, ...extraScores];

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
                    <div className="flex flex-wrap gap-1.5">
                      <Pill>ID: {area.id}</Pill>
                      <Pill>Tasks: {area.task_count}</Pill>
                    </div>
                    <div className="interactivity-row">
                      <span className="interactivity-label">Interactivity</span>
                      {allScores.length === 0 ? (
                        <span className="font-mono text-[0.84rem] text-mono-ink">
                          --
                        </span>
                      ) : (
                        <ul className="interactivity-list">
                          {allScores.map(({ key, label, xnuName, description, score }) => {
                            const tooltipId = `interactivity-tooltip-${area.id}-${key}`;
                            const tooltipActive = activeTooltipId === tooltipId;

                            return (
                              <li
                                key={key}
                                className="interactivity-chip"
                                tabIndex={0}
                                aria-describedby={tooltipActive ? tooltipId : undefined}
                                onMouseEnter={() => setActiveTooltipId(tooltipId)}
                                onMouseLeave={() =>
                                  setActiveTooltipId((current) => (
                                    current === tooltipId ? null : current
                                  ))
                                }
                                onFocus={() => setActiveTooltipId(tooltipId)}
                                onBlur={() =>
                                  setActiveTooltipId((current) => (
                                    current === tooltipId ? null : current
                                  ))
                                }
                              >
                                <span className="interactivity-chip-name">{label}:</span>
                                <span className="interactivity-chip-value">{score}</span>
                                {tooltipActive && (
                                  <span
                                    className="interactivity-chip-tooltip"
                                    role="tooltip"
                                    id={tooltipId}
                                  >
                                    <span className="interactivity-chip-tooltip-title">
                                      {label} ({key})
                                    </span>
                                    <span>XNU bucket: {xnuName}</span>
                                    <span>{description}</span>
                                  </span>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>
                  </article>
                );
              })
            )}
      </div>
    </div>
  );
}
