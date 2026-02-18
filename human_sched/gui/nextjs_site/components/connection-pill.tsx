"use client";

import type { ConnectionStatus } from "@/lib/use-event-stream";

interface ConnectionPillProps {
  status: ConnectionStatus;
}

const LABELS: Record<ConnectionStatus, string> = {
  connected: "Live SSE",
  reconnecting: "Reconnecting...",
  disconnected: "Disconnected",
};

export function ConnectionPill({ status }: ConnectionPillProps) {
  const healthy = status === "connected";

  return (
    <div className={`connection-pill ${healthy ? "connection-pill-live" : "connection-pill-warn"}`}>
      {LABELS[status]}
    </div>
  );
}
