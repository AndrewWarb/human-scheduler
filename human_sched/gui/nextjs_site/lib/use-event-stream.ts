"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { SchedulerEvent } from "./types";

const EVENT_TYPES = ["info", "quantum_expire", "sched_tick", "preemption"];

export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";

export function useEventStream(
  lastEventId: number | null,
  onEvent: (event: SchedulerEvent) => void,
) {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const onEventRef = useRef(onEvent);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  const connect = useCallback(() => {
    const base = process.env.NEXT_PUBLIC_API_URL ?? "";
    const afterQuery = lastEventId != null ? `?after=${lastEventId}` : "";
    const source = new EventSource(`${base}/api/events/stream${afterQuery}`);

    source.onopen = () => setStatus("connected");
    source.onerror = () => setStatus("reconnecting");

    const handler = (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data) as SchedulerEvent;
        onEventRef.current(payload);
      } catch {
        // Ignore malformed payloads
      }
    };

    for (const type of EVENT_TYPES) {
      source.addEventListener(type, handler);
    }
    source.onmessage = handler;

    return source;
  }, [lastEventId]);

  useEffect(() => {
    const source = connect();
    return () => {
      source.close();
      setStatus("disconnected");
    };
  }, [connect]);

  return status;
}
