"use client";

interface CardProps {
  children: React.ReactNode;
  hero?: boolean;
  className?: string;
}

export function Card({ children, hero, className = "" }: CardProps) {
  const base = "glass-card";
  const variant = hero ? "glass-card-hero" : "";
  return <article className={`${base} ${variant} ${className}`}>{children}</article>;
}
