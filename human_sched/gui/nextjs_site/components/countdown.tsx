"use client";

import { useEffect, useState } from "react";

interface CountdownProps {
  endAt: string | null | undefined;
  paused?: boolean;
}

function format(remainingMs: number): string {
  if (!Number.isFinite(remainingMs) || remainingMs <= 0) return "00:00:00";
  const total = Math.floor(remainingMs / 1000);
  const h = String(Math.floor(total / 3600)).padStart(2, "0");
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

export function Countdown({ endAt, paused = false }: CountdownProps) {
  const [nowMs, setNowMs] = useState(0);

  useEffect(() => {
    if (!endAt) return;
    const id = setTimeout(() => {
      setNowMs(Date.now());
    }, 0);
    return () => clearTimeout(id);
  }, [endAt, paused]);

  useEffect(() => {
    if (!endAt || paused) return;
    const id = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => clearInterval(id);
  }, [endAt, paused]);

  const display =
    !endAt || nowMs <= 0
      ? "--:--:--"
      : format(new Date(endAt).getTime() - nowMs);

  return (
    <span className="font-mono text-[clamp(1.2rem,2.5vw,1.8rem)] tracking-wider">
      {display}
    </span>
  );
}
