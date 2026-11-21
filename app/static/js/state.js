// Shared state of the current ticket.
export const STEPS = ["product", "audience", "channel", "topic", "scope", "evidence", "comparison", "timing", "output"];

export const state = {
  q: null,               // questionnaire.json
  segments: [],          // question 1 options
  route: null,           // live routing summary from /api/route
  answers: freshAnswers(),
  confirmed: new Set(),  // compound steps the user confirmed
  current: "product",
  result: null,
  ticketId: null,
  ticketNo: 1,
  status: null,
  settings: {},
  sessionId: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())).slice(0, 36),
  usability: { startedAt: performance.now(), shownAt: performance.now(), times: {}, backSteps: 0, firstCopyMs: null },
  knownRules: new Set(),
};

export function freshAnswers() {
  return { facts: {}, use_date: new Date().toISOString().slice(0, 10), on_market_before: "unknown", language: "en", tone: "factual", comparison: "none" };
}

export function today() { return new Date().toISOString().slice(0, 10); }

export function labelOf(list, id, lang = "en") {
  const o = (list || []).find((x) => x.id === id);
  return o ? (lang === "de" ? o.label_de || o.label_en : o.label_en) : id;
}

export function cleanAnswers() {
  // Only what the API accepts; empty values are left out.
  const a = {};
  for (const [k, v] of Object.entries(state.answers)) {
    if (k === "facts") continue;
    if (v !== undefined && v !== null && v !== "") a[k] = v;
  }
  const facts = {};
  for (const [k, v] of Object.entries(state.answers.facts || {})) if (v !== "" && v != null) facts[k] = String(v);
  a.facts = facts;
  return a;
}
