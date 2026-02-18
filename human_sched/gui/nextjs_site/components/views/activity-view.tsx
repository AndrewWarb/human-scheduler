"use client";

import { useApp } from "@/lib/app-context";
import { Card } from "../card";
import { Pill } from "../pill";

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function ActivityView() {
  const { state } = useApp();
  const reversed = [...state.events].reverse();

  return (
    <div className="animate-[fade-in_0.25s_ease]">
      <Card>
        <p className="section-eyebrow">Notifications &amp; Activity</p>
        <div className="grid gap-2.5">
          {reversed.length === 0 ? (
            <div className="text-muted italic">No events yet.</div>
          ) : (
            reversed.map((event) => (
              <article
                key={event.event_id}
                className="surface-item"
              >
                <div className="flex flex-wrap gap-1.5">
                  <Pill>{event.event_type}</Pill>
                  <Pill>{formatTimestamp(event.timestamp)}</Pill>
                  <Pill>source:{event.source ?? "unknown"}</Pill>
                </div>
                <p>{event.message ?? ""}</p>
                <p className="font-mono text-[0.84rem] text-mono-ink">
                  event_id={event.event_id}
                  {event.related_task_id != null &&
                    ` | task_id=${event.related_task_id}`}
                </p>
              </article>
            ))
          )}
        </div>
      </Card>
    </div>
  );
}
