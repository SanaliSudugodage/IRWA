// src/App.jsx
import React, { useEffect, useMemo, useState } from "react";
import {
  runDebate,
  cancelDebate,
  genArgument,
  genCounter,
  judgeRound,
  reconfigure,
  API_BASE,
  API_KEY,
} from "./api";
import { PointList } from "./components/PointList";
import { Scorecard } from "./components/Scorecard";
import { jsPDF } from "jspdf";
import { splitLines, prependAreaHint, toText } from "./utils";

/* -------------------------------- UI helpers ------------------------------- */
function Badge({ children, kind }) {
  return <span className={`badge ${kind || ""}`}>{children}</span>;
}
function Section({ title, children, right }) {
  return (
    <div className="section">
      <div className="section-head">
        <h2>{title}</h2>
        <div>{right}</div>
      </div>
      <div>{children}</div>
    </div>
  );
}

/* ---------- normalize any debate report shape coming from backend ----------- */
function normalizeDebateReport(r) {
  const pro = [];
  const con = [];
  const toPoint = (text, cites, kind) =>
    text ? { text, citations: Array.isArray(cites) ? cites : [], kind } : null;

  if (!r) return { pro, con, judge: null };

  // Legacy: arrays on top-level
  if (Array.isArray(r.pro_points) || Array.isArray(r.con_points)) {
    return { pro: r.pro_points || [], con: r.con_points || [], judge: r.judge || null };
  }
  // Legacy: nested pro/con objects
  if (r.pro?.points || r.con?.points) {
    return { pro: r.pro?.points || [], con: r.con?.points || [], judge: r.judge || null };
  }

  // Modern orchestrator: DebateReport with turns[]
  if (Array.isArray(r.turns)) {
    for (const t of r.turns) {
      if (t?.pro || t?.con) {
        const P = t.pro || {};
        const C = t.con || {};
        const pArg = toPoint(P.argument_point, P.argument_citations, "argument");
        const pReb = toPoint(P.rebuttal, P.rebuttal_citations, "rebuttal");
        const cArg = toPoint(C.argument_point, C.argument_citations, "argument");
        const cReb = toPoint(C.rebuttal, C.rebuttal_citations, "rebuttal");
        if (pArg) pro.push(pArg);
        if (pReb) pro.push(pReb);
        if (cArg) con.push(cArg);
        if (cReb) con.push(cReb);
        continue;
      }
      // Very old: per-turn with side/argument/rebuttal
      if (t?.side) {
        if (t.side === "pro") {
          const a = toPoint(t.argument_point, t.argument_citations, "argument");
          const r_ = toPoint(t.rebuttal, t.rebuttal_citations, "rebuttal");
          if (a) pro.push(a);
          if (r_) con.push(r_);
        } else {
          const a = toPoint(t.argument_point, t.argument_citations, "argument");
          const r_ = toPoint(t.rebuttal, t.rebuttal_citations, "rebuttal");
          if (a) con.push(a);
          if (r_) pro.push(r_);
        }
      }
    }
    const judge = {
      winner: r.final_winner || "—",
      scores: {
        pro: r?.scoreboard?.pro_points ?? "—",
        con: r?.scoreboard?.con_points ?? "—",
      },
      explanation: r.final_justification || "",
    };
    return { pro, con, judge };
  }

  return { pro, con, judge: r.judge || null };
}

/* ----------------------------- IR admin helpers ---------------------------- */
// Simple fetch helper so this file can toggle IR without touching api.js.
async function irFetch(base, key, path, { method = "GET", body, isForm = false } = {}) {
  const headers = isForm
    ? { Authorization: `Bearer ${key}` }
    : { "Content-Type": "application/json", Authorization: `Bearer ${key}` };
  const res = await fetch(`${base.replace(/\/+$/, "")}${path}`, {
    method,
    headers,
    body,
  });
  if (!res.ok) throw new Error(await res.text());
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

export default function App() {
  /* ------------------------------- Config ---------------------------------- */
  const [apiBase, setApiBase] = useState(API_BASE);
  const [apiKey, setApiKey] = useState(API_KEY);
  const [showKey, setShowKey] = useState(false);

  const openDocsHref = useMemo(
    () => `${apiBase.replace(/\/+$/, "")}/docs`,
    [apiBase]
  );
  function applyConfig() {
    reconfigure({ base: apiBase, key: apiKey });
    refreshIrStats(); // refresh after applying
  }

  /* -------------------------------- IR panel ------------------------------- */
  const [irStats, setIrStats] = useState(null);
  const [irBusy, setIrBusy] = useState(false);

  async function refreshIrStats() {
    try {
      const data = await irFetch(apiBase, apiKey, "/ir/stats");
      setIrStats(data);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("IR stats failed:", e);
      setIrStats(null);
    }
  }

  async function onIrToggle() {
    if (irBusy) return;
    try {
      setIrBusy(true);
      const desired = !(irStats?.use_ir ?? irStats?.ir_enabled ?? false);
      await irFetch(apiBase, apiKey, "/ir/toggle", {
        method: "POST",
        body: JSON.stringify({ use_ir: desired }), // avoid 422s
      });
      await refreshIrStats();
    } catch (e) {
      alert("Failed to toggle IR:\n" + (e?.message || e));
    } finally {
      setIrBusy(false);
    }
  }

  async function onIrReindex() {
    try {
      setIrBusy(true);
      await irFetch(apiBase, apiKey, "/ir/reindex", { method: "POST" });
      await refreshIrStats();
      alert("Reindex complete.");
    } catch (e) {
      alert("Reindex failed:\n" + (e?.message || e));
    } finally {
      setIrBusy(false);
    }
  }

  // MULTI-FILE upload (server reindexes automatically if you implemented that)
  async function onIrUpload(ev) {
    const flist = ev.target.files;
    if (!flist || flist.length === 0) return;

    const form = new FormData();
    for (const f of flist) form.append("files", f);
    try {
      setIrBusy(true);
      await irFetch(apiBase, apiKey, "/ir/upload", { method: "POST", body: form, isForm: true });
      await refreshIrStats();
      alert(`Uploaded ${flist.length} file(s).`);
    } catch (e) {
      alert("Upload failed:\n" + (e?.message || e));
    } finally {
      setIrBusy(false);
      ev.target.value = "";
    }
  }

  // Local per-call IR switches (default mirror global IR)
  const [useIrForRun, setUseIrForRun] = useState(false);
  const [manualUseIr, setManualUseIr] = useState(false);

  useEffect(() => {
    refreshIrStats();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Mirror global IR when stats change
  useEffect(() => {
    const g = (irStats && (irStats.use_ir ?? irStats.ir_enabled));
    if (typeof g === "boolean") {
      setUseIrForRun(g);
      setManualUseIr(g);
    }
  }, [irStats]);

  /* --------------------------------- Tabs ---------------------------------- */
  const [tab, setTab] = useState("auto"); // 'auto' | 'manual'

  /* ----------------------------- Shared inputs ----------------------------- */
  const [motion, setMotion] = useState("Universal Basic Income should be implemented");
  const [area, setArea] = useState("");

  /* ----------------------------- Automated run ----------------------------- */
  const [rounds, setRounds] = useState(2);
  const [opener, setOpener] = useState("pro");
  const [autoResult, setAutoResult] = useState(null);
  const [running, setRunning] = useState(false);

  // stop/cancel support
  const [debateAbort, setDebateAbort] = useState(null); // AbortController
  const [debateReqId, setDebateReqId] = useState(null); // server-side cancel id

  function newRequestId() {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
    return "rid-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
    }

  async function onRunDebate() {
    try {
      setRunning(true);
      setAutoResult(null);

      const ctrl = new AbortController();
      setDebateAbort(ctrl);
      const rid = newRequestId();
      setDebateReqId(rid);

      const data = await runDebate(
        { motion, area, rounds, opener, use_ir: useIrForRun },
        { signal: ctrl.signal, requestId: rid }
      );

      setAutoResult(data);
    } catch (e) {
      if (e?.code === "ERR_CANCELED" || e?.name === "CanceledError" || e?.name === "AbortError") {
        alert("Debate canceled.");
      } else {
        alert("Failed to run debate:\n" + (e?.message || e));
      }
    } finally {
      setRunning(false);
      setDebateAbort(null);
      setDebateReqId(null);
    }
  }

  async function onStopDebate() {
    try {
      if (debateReqId) {
        // ask server to cancel as well
        await cancelDebate(debateReqId);
      }
      debateAbort?.abort();
    } catch {
      // ignore
    }
  }

  const { pro: autoProPoints, con: autoConPoints, judge: autoJudge } = useMemo(
    () => normalizeDebateReport(autoResult),
    [autoResult]
  );

  /* --------------------------------- Manual -------------------------------- */
  const [speakSide, setSpeakSide] = useState("pro");
  const [myPoint, setMyPoint] = useState("");
  const [proPoints, setProPoints] = useState([]);
  const [conPoints, setConPoints] = useState([]);
  const [manualJudge, setManualJudge] = useState(null);
  const [busy, setBusy] = useState(false);

  function pushPoints(side, pts) {
    const arr = Array.isArray(pts) ? pts : [pts];
    if (side === "pro") setProPoints((p) => [...p, ...arr]);
    else setConPoints((p) => [...p, ...arr]);
  }
  function clearManual() {
    setProPoints([]);
    setConPoints([]);
    setMyPoint("");
    setManualJudge(null);
  }

  async function onAddMyPoint() {
    if (!myPoint.trim()) return;
    pushPoints(speakSide, { text: myPoint.trim(), citations: [], kind: "argument" });
    setMyPoint("");
  }

  async function onGenerateForSide() {
    try {
      setBusy(true);
      const mot = prependAreaHint(motion, area);
      const data = await genArgument({
        motion: mot,
        stance: speakSide,
        area,
        use_ir: manualUseIr,
      });
      const pts = (data?.points || []).map((p) => ({ ...p, kind: "argument" }));
      pushPoints(speakSide, pts);
    } catch (e) {
      alert("Generate for side failed:\n" + (e?.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function onCounterLast() {
    try {
      setBusy(true);
      const opp = (speakSide === "pro" ? conPoints : proPoints).map(toText).filter(Boolean);
      if (opp.length === 0) {
        alert("There are no opponent points yet to counter.");
        return;
      }
      const data = await genCounter({
        motion,
        opponent_points: opp,
        area,
        use_ir: manualUseIr,
      });
      const pts = (data?.rebuttals || data?.points || data || []).map((rb) => ({
        text: rb.counterclaim || rb.text || "",
        citations: rb.citations || [],
        kind: "rebuttal",
      }));
      pushPoints(speakSide, pts);
    } catch (e) {
      alert("Counter failed:\n" + (e?.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function onJudgeNow() {
    try {
      setBusy(true);
      const data = await judgeRound({
        motion,
        pro_points: proPoints,
        con_points: conPoints,
      });
      setManualJudge(data);
    } catch (e) {
      alert("Judge failed:\n" + (e?.message || e));
    } finally {
      setBusy(false);
    }
  }

  /* -------------------------------- Export --------------------------------- */
  function exportJSON() {
    const payload =
      tab === "auto"
        ? autoResult
        : { motion, area, pro_points: proPoints, con_points: conPoints, judge: manualJudge };
    const blob = new Blob([JSON.stringify(payload || {}, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "debate_result.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  function exportPDF() {
    const doc = new jsPDF({ unit: "pt", format: "a4" });
    let y = 40;

    function title(t) { doc.setFont("helvetica", "bold"); doc.setFontSize(16); doc.text(t, 40, y); y += 18; }
    function body(t)  {
      doc.setFont("helvetica", "normal"); doc.setFontSize(12);
      for (const line of splitLines(t, 95)) { doc.text(line, 40, y); y += 16; }
      y += 10;
    }
    function list(label, items) {
      title(label);
      if (!items || items.length === 0) { body("—"); return; }
      items.forEach((p, i) => body(`${i + 1}. ${toText(p)}`));
    }

    title("AI Debate Report");
    body(`Motion: ${motion}`);
    if (area) body(`Area: ${area}`);
    body(`Generated at: ${new Date().toLocaleString()}`);

    if (tab === "auto" && autoResult) {
      list("Pro Points", autoProPoints);
      list("Con Points", autoConPoints);
      if (autoJudge) {
        title("Judge");
        body(`Winner: ${autoJudge.winner ?? "—"}`);
        body(`Scores: pro ${autoJudge.scores?.pro ?? "—"} / con ${autoJudge.scores?.con ?? "—"}`);
        if (autoJudge.explanation) body(`Explanation: ${autoJudge.explanation}`);
      }
    } else {
      list("Pro Points", proPoints);
      list("Con Points", conPoints);
      if (manualJudge) {
        title("Judge");
        body(`Winner: ${manualJudge.winner ?? "—"}`);
        body(`Pro total: ${manualJudge.pro_total ?? "—"}  |  Con total: ${manualJudge.con_total ?? "—"}`);
        if (manualJudge.tie_breaker) body(`Note: ${manualJudge.tie_breaker}`);
      }
    }

    doc.save("debate_report.pdf");
  }

  /* -------------------------------- Render --------------------------------- */
  const sizeBytes = irStats?.size_bytes ?? (irStats?.size_kb ? irStats.size_kb * 1024 : null);
  const sizeHuman = sizeBytes ? `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB` : "—";
  const irOn = !!(irStats?.use_ir ?? irStats?.ir_enabled);

  return (
    <div className="wrap">
      <header className="top">
        <h1>AI Debate System</h1>
        <div className="subtitle">Automated & manual tools • IR + LLM + NLP</div>
      </header>

      {/* Configuration */}
      <Section
        title="Configuration"
        right={<a href={openDocsHref} target="_blank" rel="noreferrer" className="link">Open API Docs</a>}
      >
        <div className="grid2">
          <label className="field">
            <div>API Base</div>
            <input value={apiBase} onChange={(e) => setApiBase(e.target.value)} />
          </label>
          <label className="field">
            <div>API Key</div>
            <div className="row" style={{ gap: 8, alignItems: "center" }}>
              <input
                type={showKey ? "text" : "password"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <button className="btn secondary" onClick={() => setShowKey(s => !s)}>
                {showKey ? "Hide" : "Show"}
              </button>
            </div>
          </label>
        </div>
        <div className="row gap mt">
          <Badge>CORS: localhost:5173</Badge>
          <Badge>Auth: Bearer</Badge>
          <button className="btn" onClick={applyConfig}>Apply</button>
        </div>
      </Section>

      {/* Corpus & IR */}
      <Section
        title="Corpus & IR"
        right={
          <button className="btn" onClick={onIrToggle} disabled={irBusy}>
            {irOn ? "Turn IR Off" : "Turn IR On"}
          </button>
        }
      >
        <div className="grid2">
          <div className="card">
            <div className="row" style={{ gap: 10 }}>
              <input type="file" multiple onChange={onIrUpload} disabled={irBusy} />
              <button className="btn secondary" onClick={onIrReindex} disabled={irBusy}>Reindex</button>
            </div>
          </div>
          <div className="card">
            <div className="grid2">
              <div>
                <div className="label">Corpus dir</div>
                <div className="badge">{irStats?.corpus_dir || "—"}</div>
              </div>
              <div>
                <div className="label">Files</div>
                <div className="badge">{irStats?.files ?? "—"}</div>
              </div>
              <div>
                <div className="label">Size</div>
                <div className="badge">{sizeHuman}</div>
              </div>
              <div>
                <div className="label">IR</div>
                <div className={`badge ${irOn ? "ok" : "warn"}`}>{irOn ? "On" : "Off"}</div>
              </div>
            </div>
          </div>
        </div>
      </Section>

      {/* Tabs */}
      <div className="tabs">
        <button className={`tab ${tab === "auto" ? "active" : ""}`} onClick={() => setTab("auto")}>
          Automated Debate
        </button>
        <button className={`tab ${tab === "manual" ? "active" : ""}`} onClick={() => setTab("manual")}>
          Manual (Endpoints)
        </button>
      </div>

      {/* Shared Inputs */}
      <div className="card">
        <label className="field">
          <div>Motion</div>
          <textarea rows={3} value={motion} onChange={(e) => setMotion(e.target.value)} />
        </label>
        <div className="grid2">
          <label className="field">
            <div>Knowledge area (steers IR)</div>
            <input placeholder="e.g., EU healthcare policy" value={area} onChange={(e) => setArea(e.target.value)} />
          </label>

          {tab === "auto" ? (
            <div className="grid2">
              <label className="field">
                <div>Rounds</div>
                <input type="number" min={1} max={10} value={rounds} onChange={(e) => setRounds(e.target.value)} />
              </label>
              <label className="field">
                <div>Opener</div>
                <select value={opener} onChange={(e) => setOpener(e.target.value)}>
                  <option value="pro">Pro (affirmative)</option>
                  <option value="con">Con (negative)</option>
                </select>
              </label>
              <label className="field">
                <div>Use IR for this run</div>
                <div className="row" style={{ alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={!!useIrForRun}
                    onChange={(e) => setUseIrForRun(e.target.checked)}
                  />
                  <span className="muted">{useIrForRun ? "On" : "Off"}</span>
                </div>
              </label>
            </div>
          ) : (
            <div className="grid2">
              <label className="field">
                <div>Side to speak</div>
                <select value={speakSide} onChange={(e) => setSpeakSide(e.target.value)}>
                  <option value="pro">Pro</option>
                  <option value="con">Con</option>
                </select>
              </label>
              <label className="field">
                <div>Use IR (manual calls)</div>
                <div className="row" style={{ alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={!!manualUseIr}
                    onChange={(e) => setManualUseIr(e.target.checked)}
                  />
                  <span className="muted">{manualUseIr ? "On" : "Off"}</span>
                </div>
              </label>
            </div>
          )}
        </div>
      </div>

      {/* Panels */}
      {tab === "auto" ? (
        <Section
          title="Automated Debate"
          right={
            <div className="row gap">
              <button className="btn" onClick={exportJSON} disabled={!autoResult}>Export JSON</button>
              <button className="btn" onClick={exportPDF} disabled={!autoResult}>Export PDF</button>
            </div>
          }
        >
          <div className="row gap">
            <button className="btn primary" onClick={onRunDebate} disabled={running}>
              {running ? "Running…" : "Run Debate"}
            </button>
            {running && (
              <button className="btn danger" onClick={onStopDebate}>
                Stop
              </button>
            )}
            {!autoResult && <Badge kind="muted">No result yet</Badge>}
          </div>

          {autoResult && (
            <div className="grid2 mt">
              <PointList title="Pro Points" points={autoProPoints} />
              <PointList title="Con Points" points={autoConPoints} />
              <Scorecard judge={autoJudge} />
            </div>
          )}
        </Section>
      ) : (
        <>
          <Section
            title="Manual (Endpoint-by-endpoint)"
            right={
              <div className="row gap">
                <button className="btn" onClick={exportJSON} disabled={proPoints.length + conPoints.length === 0 && !manualJudge}>Export JSON</button>
                <button className="btn" onClick={exportPDF} disabled={proPoints.length + conPoints.length === 0 && !manualJudge}>Export PDF</button>
              </div>
            }
          >
            <div className="card">
              <div className="grid2">
                <label className="field">
                  <div>Your point (optional)</div>
                  <textarea
                    rows={3}
                    placeholder={`Type a ${speakSide.toUpperCase()} point to add…`}
                    value={myPoint}
                    onChange={(e) => setMyPoint(e.target.value)}
                  />
                </label>
                <div className="field">
                  <div>Actions</div>
                  <div className="row gap">
                    <button className="btn" onClick={onAddMyPoint} disabled={busy || !myPoint.trim()}>Add My Point</button>
                    <button className="btn" onClick={onGenerateForSide} disabled={busy}>Generate for Side</button>
                    <button className="btn" onClick={onCounterLast} disabled={busy}>Counter Last</button>
                    <button className="btn" onClick={onJudgeNow} disabled={busy || (proPoints.length + conPoints.length === 0)}>Judge now</button>
                    <button className="btn" onClick={clearManual} disabled={busy}>Clear</button>
                  </div>
                </div>
              </div>
            </div>

            <div className="grid2 mt">
              <PointList title="Pro Points" points={proPoints} />
              <PointList title="Con Points" points={conPoints} />
            </div>

            <Scorecard judge={manualJudge} />
          </Section>
        </>
      )}
    </div>
  );
}
