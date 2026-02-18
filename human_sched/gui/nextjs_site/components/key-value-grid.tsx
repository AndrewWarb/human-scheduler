"use client";

interface KeyValueGridProps {
  rows: [string, string][];
}

export function KeyValueGrid({ rows }: KeyValueGridProps) {
  return (
    <div className="kv-grid">
      {rows.map(([key, value]) => (
        <div key={key} className="contents">
          <div className="kv-grid-key">{key}</div>
          <div className="kv-grid-value">{value}</div>
        </div>
      ))}
    </div>
  );
}
