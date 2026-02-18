"use client";

interface PillProps {
  children: React.ReactNode;
  variant?: "default" | "accent" | "warning";
}

const VARIANT_CLASSES: Record<string, string> = {
  default: "ui-pill-default",
  accent: "ui-pill-accent",
  warning: "ui-pill-warning",
};

export function Pill({ children, variant = "default" }: PillProps) {
  return (
    <span className={`ui-pill ${VARIANT_CLASSES[variant]}`}>
      {children}
    </span>
  );
}
