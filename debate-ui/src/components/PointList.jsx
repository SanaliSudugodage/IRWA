import React from "react";
import { toText } from "../utils";

export function PointList({ title, points }) {
  const clean = Array.isArray(points) ? points : [];
  return (
    <div className="card">
      <h3 style={{marginTop:0}}>{title}</h3>
      {clean.length === 0 ? (
        <p className="muted">No points.</p>
      ) : (
        <ol className="list">
          {clean.map((p, i) => (
            <li key={i}>
              {p?.kind && (
                <span className={`chip ${p.kind === "counter" ? "chip-red" : "chip-green"}`}>
                  {p.kind === "counter" ? "Counter" : "Argument"}
                </span>
              )}
              <div className="point-text">{toText(p)}</div>
              {p && typeof p === "object" && Array.isArray(p.citations) && p.citations.length > 0 && (
                <div className="citations">
                  {p.citations.map((c, j) => (
                    <span key={j} className="citation">
                      {typeof c === "string" ? c : (c.url || c.source || "source")}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
} 
