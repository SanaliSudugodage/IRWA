export const splitLines = (text) =>
  (text || '')
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean)

export const prependAreaHint = (motion, area) =>
  (area && area.trim())
    ? `${motion.trim()}  [Topic: ${area.trim()}]`
    : motion.trim()
