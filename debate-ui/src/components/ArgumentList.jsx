// src/components/ArgumentList.jsx
import { normalizePoints } from "../utils";

export function ArgumentList({ title, points = [] }) {
  const safe = normalizePoints(points);
  return (
    <div className="p-4 rounded-xl bg-slate-800/40">
      <h3 className="font-semibold mb-2">{title}</h3>
      {safe.length === 0 ? (
        <div className="opacity-70 text-sm">No points.</div>
      ) : (
        <ol className="list-decimal ml-5 space-y-1">
          {safe.map((t, i) => (
            <li key={i}>{t}</li>
          ))}
        </ol>
      )}
    </div>
  );
}
