"use client";

import { useApp } from "@/lib/app-context";
import { Card } from "../card";
import { KeyValueGrid } from "../key-value-grid";

export function SettingsView() {
  const { state } = useApp();
  const meta = state.meta;
  const diag = state.diagnostics;

  const adapterRows: [string, string][] = meta
    ? [
        ["Adapter", meta.adapter?.name ?? "--"],
        ["Version", meta.adapter?.version ?? "--"],
        ["Contract", meta.contract_version ?? "--"],
        ["Base URL", meta.base_url ?? "--"],
        [
          "Capabilities",
          (meta.adapter?.capabilities ?? []).join(", ") || "--",
        ],
      ]
    : [];

  const diagRows: [string, string][] = diag
    ? [
        ["event_stream_status", diag.event_stream_status],
        [
          "event_stream_active_clients",
          String(diag.event_stream_active_clients),
        ],
        ["last_event_timestamp", diag.last_event_timestamp ?? "--"],
        ["event_lag_ms", diag.event_lag_ms != null ? String(diag.event_lag_ms) : "--"],
        [
          "last_successful_command_time",
          diag.last_successful_command_time ?? "--",
        ],
        ["last_command_error", diag.last_command_error ?? "--"],
        [
          "dropped_event_count",
          diag.dropped_event_count != null
            ? String(diag.dropped_event_count)
            : "--",
        ],
        [
          "event_stream_dropped_clients",
          diag.event_stream_dropped_clients != null
            ? String(diag.event_stream_dropped_clients)
            : "--",
        ],
        [
          "event_stream_retried_writes",
          diag.event_stream_retried_writes != null
            ? String(diag.event_stream_retried_writes)
            : "--",
        ],
        [
          "last_event_stream_error",
          diag.last_event_stream_error ?? "--",
        ],
        [
          "scheduler_connection_status",
          diag.scheduler_connection_status,
        ],
        ["scheduler_base_url", diag.scheduler_base_url],
      ]
    : [];

  return (
    <div className="animate-[fade-in_0.25s_ease]">
      <div className="grid grid-cols-2 gap-3.5 max-[920px]:grid-cols-1">
        <Card>
          <p className="section-eyebrow">Adapter Metadata</p>
          {adapterRows.length > 0 ? (
            <KeyValueGrid rows={adapterRows} />
          ) : (
            <div className="text-muted italic">Loading...</div>
          )}
        </Card>

        <Card>
          <p className="section-eyebrow">Diagnostics</p>
          {diagRows.length > 0 ? (
            <KeyValueGrid rows={diagRows} />
          ) : (
            <div className="text-muted italic">Loading...</div>
          )}
        </Card>
      </div>
    </div>
  );
}
