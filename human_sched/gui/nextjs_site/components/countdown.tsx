"use client";

import { useEffect, useState } from "react";

interface CountdownProps {
  endAt: string | null | undefined;
}

function format(remainingMs: number): string {
  if (!Number.isFinite(remainingMs) || remainingMs <= 0) return "00:00:00";
  const total = Math.floor(remainingMs / 1000);
  const h = String(Math.floor(total / 3600)).padStart(2, "0");
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

export function Countdown({ endAt }: CountdownProps) {
  const [display, setDisplay] = useState("--:--:--");

  useEffect(() => {
    if (!endAt) {
      setDisplay("--:--:--");
      return;
    }

    const tick = () => {
      const remaining = new Date(endAt).getTime() - Date.now();
      setDisplay(format(remaining));
    };

    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [endAt]);

  return (
    <span className="font-mono text-[clamp(1.2rem,2.5vw,1.8rem)] tracking-wider">
      {display}
    </span>
  );
}
