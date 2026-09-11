const LIMIT = 50;

const clone = (value) => JSON.parse(JSON.stringify(value));
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);

export function createHistory(value) {
  return { past: [], present: clone(value), future: [] };
}

export function recordHistory(history, next, previous = history.present) {
  if (same(previous, next)) return { ...history, present: clone(next) };
  return {
    past: [...history.past, clone(previous)].slice(-LIMIT),
    present: clone(next),
    future: [],
  };
}

export function undoHistory(history) {
  if (!history.past.length) return history;
  const previous = history.past.at(-1);
  return {
    past: history.past.slice(0, -1),
    present: clone(previous),
    future: [clone(history.present), ...history.future].slice(0, LIMIT),
  };
}

export function redoHistory(history) {
  if (!history.future.length) return history;
  const next = history.future[0];
  return {
    past: [...history.past, clone(history.present)].slice(-LIMIT),
    present: clone(next),
    future: history.future.slice(1),
  };
}
