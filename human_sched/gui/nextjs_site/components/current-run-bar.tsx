"use client";

import type { Dispatch } from "@/lib/types";
import { Countdown } from "./countdown";

interface CurrentRunBarProps {
  dispatch: Dispatch | null;
}

export function CurrentRunBar({ dispatch }: CurrentRunBarProps) {
  const title = dispatch?.task.title ?? "No active task";
  const meta = dispatch
    ? `${dispatch.life_area.name} • ${dispatch.task.urgency_label} • ${dispatch.decision}`
    : "Press What Next to dispatch work.";

  return (
    <section className="current-run-bar">
      <div>
        <p className="section-eyebrow text-run-eyebrow">Currently Running</p>
        <h2>{title}</h2>
        <p className="current-run-meta">{meta}</p>
      </div>
      <Countdown endAt={dispatch?.focus_block_end_at} />
    </section>
  );
}
