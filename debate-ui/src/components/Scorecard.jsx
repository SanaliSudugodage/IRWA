// src/components/Scorecard.jsx
import React from "react";

export function Scorecard({ judge }) {
  if (!judge) return null;

  // --- Normalize across both shapes (auto + manual) ---
  const winner =
    judge.winner ||
    judge.final_winner ||
    (Number.isFinite(judge.pro_total) && Number.isFinite(judge.con_total)
      ? judge.pro_total === judge.con_total
        ? "tie"
        : judge.pro_total > judge.con_total
        ? "pro"
        : "con"
      : "—");

  const proTotal =
    judge?.scores?.pro ??
    judge?.pro_total ??
    (Number.isFinite(judge?.pro_total) ? judge.pro_total : "—");

  const conTotal =
    judge?.scores?.con ??
    judge?.con_total ??
    (Number.isFinite(judge?.con_total) ? judge.con_total : "—");

  const explanation =
    judge.explanation ||
    judge.final_justification ||
    judge.tie_breaker ||
    judge.judge_explanation ||
    "";

  // Optional detailed subscores if present (manual judge often provides these)
  const proBreak = Array.isArray(judge.pro_breakdown) ? judge.pro_breakdown : null;
  const conBreak = Array.isArray(judge.con_breakdown) ? judge.con_breakdown : null;

  return (
    <div className="card">
      <h3>Scorecard</h3>

      <div className="grid2">
        <div>
          <div className="label">Winner</div>
          <span className={`badge ${winner}`}>{winner}</span>
        </div>

        <div>
          <div className="label">Scores</div>
          <div className="row gap">
            <span className="badge">Pro: {proTotal}</span>
            <span className="badge">Con: {conTotal}</span>
          </div>
        </div>
      </div>

      {explanation ? (
        <div className="mt">
          <div className="label">Judge’s explanation</div>
          <p className="muted">{explanation}</p>
        </div>
      ) : null}

      {(proBreak || conBreak) && (
        <div className="mt grid2">
          {proBreak && (
            <div>
              <div className="label">Pro breakdown</div>
              <ul className="muted">
                {proBreak.map((b, i) => (
                  <li key={i}>
                    {b?.criterion || b?.label || `crit ${i + 1}`}: <b>{b?.score ?? "-"}</b>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {conBreak && (
            <div>
              <div className="label">Con breakdown</div>
              <ul className="muted">
                {conBreak.map((b, i) => (
                  <li key={i}>
                    {b?.criterion || b?.label || `crit ${i + 1}`}: <b>{b?.score ?? "-"}</b>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
