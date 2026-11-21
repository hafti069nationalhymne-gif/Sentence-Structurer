// Thin wrapper around the local API (same origin, 127.0.0.1 only).
async function call(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok) {
    const err = new Error((data && data.detail) || `Request failed (${res.status})`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  questionnaire: () => call("GET", "/api/questionnaire"),
  status: () => call("GET", "/api/status"),
  route: (answers) => call("POST", "/api/route", { answers }),
  recommend: (answers, session_id, use_ai = true) => call("POST", "/api/recommend", { answers, session_id, use_ai }),
  revalidate: (answers, template_id, values) => call("POST", "/api/revalidate", { answers, template_id, values }),
  adjust: (answers, template_id, values) => call("POST", "/api/adjust", { answers, template_id, values }),
  sources: (ruleId) => call("GET", `/api/sources/${encodeURIComponent(ruleId)}`),
  search: (q) => call("GET", `/api/search?q=${encodeURIComponent(q)}`),
  settings: (patch) => call("POST", "/api/settings", patch),
  history: () => call("GET", "/api/history"),
  ticket: (id) => call("GET", `/api/history/${id}`),
  review: (body) => call("POST", "/api/review", body),
  usability: (body) => call("POST", "/api/usability", body),
  sus: (body) => call("POST", "/api/sus", body),
  event: (body) => call("POST", "/api/events", body).catch(() => null),
  clear: () => call("POST", "/api/clear", { confirm: "DELETE" }),
};
