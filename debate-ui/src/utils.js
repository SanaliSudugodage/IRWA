// src/utils.js

// prepend the user's area hint to the motion if present (used by manual flows)
export function prependAreaHint(motion, area) {
  if (!area) return motion;
  return `[${motion}] — focus area: ${area}`;
}

// split long strings to nicer lines for PDF export
export function splitLines(s = "", max = 90) {
  const words = String(s).split(/\s+/);
  const lines = [];
  let cur = [];
  let len = 0;
  for (const w of words) {
    if (len + w.length + 1 > max) {
      lines.push(cur.join(" "));
      cur = [w];
      len = w.length;
    } else {
      cur.push(w);
      len += (len ? 1 : 0) + w.length;
    }
  }
  if (cur.length) lines.push(cur.join(" "));
  return lines;
}

// Backend sometimes returns points like {text, citations: [...]}
// Normalize anything into a printable string.
export function toText(x) {
  if (!x && x !== 0) return "";
  if (typeof x === "string") return x;
  if (Array.isArray(x)) return x.map(toText).join("\n");
  if (typeof x === "object" && x.text) return String(x.text);
  try { return JSON.stringify(x); } catch { return String(x); }
}

// For ArgumentList: return clean array of strings
export function normalizePoints(points) {
  if (!Array.isArray(points)) return [];
  return points.map(toText).filter(Boolean);
}
