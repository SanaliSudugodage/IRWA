// src/api.js
import axios from "axios";

export const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";
export const API_KEY  = import.meta.env.VITE_API_KEY  || "dev-12345";

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 1000 * 60 * 15,
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${API_KEY}`,
  },
});

export function reconfigure({ base, key }) {
  if (base) api.defaults.baseURL = base.trim();
  if (key)  api.defaults.headers.Authorization = `Bearer ${key.trim()}`;
}

function errDetail(e) {
  return (
    e?.response?.data?.detail ||
    e?.response?.data?.message ||
    (typeof e?.response?.data === "string" ? e.response.data : null) ||
    e?.message ||
    String(e)
  );
}

/* ------------------------ Debate (orchestrator) ------------------------- */
/**
 * runDebate(payload, opts)
 *   payload: { motion, area, rounds, opener, use_ir }
 *   opts: { signal?, requestId? }  // for cancel/abort
 */
export async function runDebate({ motion, area, rounds, opener, use_ir }, opts = {}) {
  try {
    const payload = {
      motion,
      stance: opener || "pro",
      settings: {
        max_turns: Number(rounds) || 4,
        swap_sides_each_turn: true,
        ...(use_ir === undefined ? {} : { use_ir: !!use_ir }),
      },
      ...(area ? { area_hint: area } : {}),
    };
    const ridQS = opts.requestId ? `?request_id=${encodeURIComponent(opts.requestId)}` : "";
    const { data } = await api.post(`/debate/run${ridQS}`, payload, {
      signal: opts.signal,
    });
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
}

/** Ask server to stop an in-flight debate (pairs with AbortController on client). */
export async function cancelDebate(requestId) {
  try {
    if (!requestId) return { ok: false };
    const { data } = await api.post(`/debate/cancel?request_id=${encodeURIComponent(requestId)}`);
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
}

/* --------------------------- Agents (manual) --------------------------- */
export async function genArgument({ motion, stance, area, use_ir }) {
  try {
    const qs = use_ir === undefined ? "" : `?use_ir=${use_ir ? "true" : "false"}`;
    const payload = {
      motion,
      stance: stance || null,
      ...(area ? { area_hint: area } : {}),
    };
    const { data } = await api.post(`/agents/argument${qs}`, payload);
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
}

export async function genCounter({ motion, opponent_points, area, use_ir }) {
  try {
    const qs = use_ir === undefined ? "" : `?use_ir=${use_ir ? "true" : "false"}`;
    const payload = {
      motion,
      opponent_points: Array.isArray(opponent_points) ? opponent_points : [],
      ...(area ? { area_hint: area } : {}),
    };
    const { data } = await api.post(`/agents/counter${qs}`, payload);
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
}

function normalizePoint(x) {
  if (!x && x !== 0) return { text: "", citations: [] };
  if (typeof x === "string") return { text: x, citations: [] };
  if (Array.isArray(x)) return { text: x.join("\n"), citations: [] };
  if (typeof x === "object" && x.text !== undefined) {
    return { text: String(x.text), citations: Array.isArray(x.citations) ? x.citations : [] };
  }
  try { return { text: JSON.stringify(x), citations: [] }; } catch { return { text: String(x), citations: [] }; }
}

export async function judgeRound({ motion, pro_points, con_points }) {
  try {
    const payload = {
      motion,
      pro: { thesis: "Pro case", points: (pro_points || []).map(normalizePoint) },
      con: { thesis: "Con case", points: (con_points || []).map(normalizePoint) },
    };
    const { data } = await api.post("/agents/judge", payload);
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
}

/* ------------------------------ IR Admin ------------------------------ */
export async function irGetStats() {
  try {
    const { data } = await api.get("/ir/stats");
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
}

export async function irToggleDefault(use_ir) {
  try {
    const { data } = await api.post("/ir/toggle", { use_ir: !!use_ir });
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
}

/** Single-file upload version (matches your current backend). */
export async function irUpload(file) {
  try {
    const form = new FormData();
    form.append("file", file);
    const { data } = await api.post("/ir/upload", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
}

export async function irReindex() {
  try {
    const { data } = await api.post("/ir/reindex");
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
}
