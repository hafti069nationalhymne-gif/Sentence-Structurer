// ClaimComposer — bootstrap, drawers and session handling.
import { h, $, $$, clear, toast } from "./dom.js";
import { api } from "./api.js";
import { state, freshAnswers, cleanAnswers, labelOf } from "./state.js";
import { initTicket, renderTicket, refreshRoute, go, resetTicketStages } from "./ticket.js";
import { renderEmpty, renderResult, renderSetting, renderError } from "./composer.js";

const SUS_ITEMS = [
  "I think that I would like to use this system frequently.",
  "I found the system unnecessarily complex.",
  "I thought the system was easy to use.",
  "I think that I would need the support of a technical person to be able to use this system.",
  "I found the various functions in this system were well integrated.",
  "I thought there was too much inconsistency in this system.",
  "I would imagine that most people would learn to use this system very quickly.",
  "I found the system very cumbersome to use.",
  "I felt very confident using the system.",
  "I needed to learn a lot of things before I could get going with this system.",
];

async function boot() {
  try {
    const data = await api.questionnaire();
    state.q = data.questionnaire;
    state.segments = data.segments;
  } catch (e) {
    renderError("The local server did not answer. Close this window and start ClaimComposer again.");
    return;
  }
  initTicket({ onComplete: compose });
  await refreshStatus();
  await refreshTicketNo();
  await refreshRoute();
  renderEmpty();
  state.current = "product";
  // One orchestrated load: the ticket feeds in (CSS), then the first field appears.
  setTimeout(() => renderTicket({ focus: true }), window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 520);
  wire();
}

async function refreshStatus() {
  try {
    const s = await api.status();
    state.status = s;
    state.settings = s.settings;
    const pill = $("#mode-pill");
    pill.dataset.mode = s.mode;
    pill.textContent = s.mode === "ai" ? `AI · ${s.settings.chat_model}` : "Template mode";
    pill.title = s.message;
    $("#ai-hint").textContent = s.message;
    $("#hashes").textContent = `Library ${s.library_hash} · Knowledge ${s.knowledge_hash} · ${s.templates} templates · bound to ${s.bind_host}`;
    const dl = clear($("#model-list"));
    for (const m of (s.ollama && s.ollama.models) || []) dl.appendChild(h("option", { value: m }));
    const f = $("#settings-form");
    f.ollama_enabled.checked = s.settings.ollama_enabled;
    f.chat_model.value = s.settings.chat_model;
    f.review_mode.checked = s.settings.review_mode;
    f.usability_mode.checked = s.settings.usability_mode;
    $("#btn-sus").hidden = !s.settings.usability_mode;
  } catch { /* keep going in template mode */ }
}

async function refreshTicketNo() {
  try {
    const hist = await api.history();
    const last = hist.tickets.length ? hist.tickets[0].id : 0;
    state.ticketNo = last + 1;
  } catch { state.ticketNo = 1; }
  $("#ticket-no").textContent = `No. ${String(state.ticketNo).padStart(4, "0")}`;
}

async function compose() {
  renderSetting();
  try {
    const res = await api.recommend(cleanAnswers(), state.sessionId);
    state.result = res;
    state.ticketId = res.ticket_id;
    $("#ticket-no").textContent = `No. ${String(res.ticket_id || state.ticketNo).padStart(4, "0")}`;
    renderTicket();
    renderResult(res, { animate: true });
    if (state.settings.usability_mode) {
      api.usability({ session_id: state.sessionId, ticket_id: res.ticket_id, question_times: state.usability.times,
        back_steps: state.usability.backSteps, time_to_first_copy_ms: state.usability.firstCopyMs }).catch(() => null);
    }
  } catch (e) {
    const errs = e.data && e.data.errors ? Object.entries(e.data.errors).map(([k, v]) => `${k}: ${v}`).join("; ") : e.message;
    renderError(`Some answers need another look: ${errs}`);
  }
}

function newTicket({ keep = false } = {}) {
  const prev = state.answers;
  state.answers = freshAnswers();
  state.confirmed = new Set();
  resetTicketStages();
  if (keep) {
    // Duplicate: same answers, choose a new audience and channel.
    Object.assign(state.answers, prev, { facts: { ...prev.facts } });
    delete state.answers.audience;
    delete state.answers.channel;
    for (const s of ["scope", "evidence", "comparison", "timing", "output"]) state.confirmed.add(s);
  }
  state.result = null;
  state.ticketId = null;
  state.usability = { startedAt: performance.now(), shownAt: performance.now(), times: {}, backSteps: 0, firstCopyMs: null };
  api.event({ session_id: state.sessionId, type: keep ? "duplicate" : "new_ticket", payload: {} });
  refreshTicketNo();
  renderEmpty();
  refreshRoute().then(() => go(keep ? "audience" : "product"));
}

// ---- drawers ------------------------------------------------------------------------------
function openDrawer(id, btn) {
  for (const d of $$(".drawer")) { if (d.id !== id) d.hidden = true; }
  const d = $(`#${id}`);
  d.hidden = false;
  $$("[aria-controls]").forEach((b) => b.setAttribute("aria-expanded", b.getAttribute("aria-controls") === id ? "true" : "false"));
  d.querySelector("[data-close]").focus();
  d._opener = btn;
}
function closeDrawer(d) {
  d.hidden = true;
  $$(`[aria-controls="${d.id}"]`).forEach((b) => b.setAttribute("aria-expanded", "false"));
  if (d._opener) d._opener.focus();
}

async function renderLog() {
  const ol = clear($("#joblog"));
  let hist;
  try { hist = await api.history(); } catch { ol.appendChild(h("li", {}, "The job log could not be read.")); return; }
  if (!hist.tickets.length) { ol.appendChild(h("li", { class: "hint" }, "No tickets yet.")); return; }
  for (const t of hist.tickets) {
    const a = t.answers;
    const seg = state.segments.find((s) => s.id === a.segment);
    ol.appendChild(h("li", {},
      h("div", { class: "joblog__line" }, h("span", {}, `No. ${String(t.id).padStart(4, "0")}`), h("span", {}, t.created_at.replace("T", " ").slice(0, 16))),
      h("span", { class: "joblog__topic" }, `${t.topic_label || a.topic} · ${seg ? seg.segment_name || seg.label_en : a.segment}`),
      h("span", { class: "mono-label" }, `${labelOf(state.q.audience, a.audience)} · ${labelOf(state.q.channel, a.channel)} · ${t.n_recommendations} proofs · ${t.mode}`),
      h("div", { class: "joblog__btns" },
        h("button", { type: "button", class: "btn btn--small", onclick: () => openTicket(t.id) }, "Open"),
        h("a", { class: "btn btn--small", href: `/api/export?format=json&ticket_id=${t.id}` }, "JSON"),
        h("a", { class: "btn btn--small", href: `/api/export?format=csv&ticket_id=${t.id}` }, "CSV"),
        h("a", { class: "btn btn--small", href: `/api/export?format=md&ticket_id=${t.id}` }, "MD"))));
  }
}

async function openTicket(id) {
  const t = await api.ticket(id);
  state.answers = { facts: {}, ...t.answers, facts: { ...(t.answers.facts || {}) } };
  state.confirmed = new Set(["scope", "evidence", "comparison", "timing", "output"]);
  resetTicketStages();
  state.result = t.result;
  state.ticketId = t.id;
  state.current = null;
  $("#ticket-no").textContent = `No. ${String(t.id).padStart(4, "0")}`;
  await refreshRoute();
  renderTicket();
  renderResult(t.result, { animate: false });
  closeDrawer($("#drawer-log"));
}

function wire() {
  $("#btn-new").addEventListener("click", () => newTicket());
  $("#btn-dup").addEventListener("click", () => newTicket({ keep: true }));
  $("#btn-log").addEventListener("click", (e) => { openDrawer("drawer-log", e.currentTarget); renderLog(); });
  $("#btn-settings").addEventListener("click", (e) => { openDrawer("drawer-settings", e.currentTarget); refreshStatus(); });
  $$("[data-close]").forEach((b) => b.addEventListener("click", () => {
    const d = b.closest(".drawer, .modal");
    if (d.classList.contains("modal")) d.hidden = true; else closeDrawer(d);
  }));
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const open = $$(".drawer, .modal").find((d) => !d.hidden);
    if (open) { if (open.classList.contains("modal")) open.hidden = true; else closeDrawer(open); }
  });

  const f = $("#settings-form");
  f.addEventListener("change", async (e) => {
    const patch = {};
    if (e.target.name === "chat_model") {
      if (!e.target.checkValidity()) { toast("Model names use letters, digits and . : / - only."); return; }
      patch.chat_model = e.target.value;
    } else if (e.target.type === "checkbox") patch[e.target.name] = e.target.checked;
    else return;
    try {
      await api.settings(patch);
      await refreshStatus();
      toast("Settings saved.");
      if (state.result && (patch.review_mode !== undefined)) renderResult(state.result, { animate: false });
    } catch (err) { toast(err.message); }
  });
  f.addEventListener("submit", (e) => e.preventDefault());

  $("#btn-clear").addEventListener("click", () => { $("#clear-confirm").hidden = false; $("#btn-clear-cancel").focus(); });
  $("#btn-clear-cancel").addEventListener("click", () => { $("#clear-confirm").hidden = true; $("#btn-clear").focus(); });
  $("#btn-clear-yes").addEventListener("click", async () => {
    await api.clear();
    $("#clear-confirm").hidden = true;
    toast("All local data was deleted.");
    newTicket();
  });

  // SUS
  const list = $("#sus-items");
  SUS_ITEMS.forEach((text, i) => list.appendChild(h("li", {}, text,
    h("div", { class: "sus__scale", role: "radiogroup", "aria-label": `Statement ${i + 1}` },
      ...[1, 2, 3, 4, 5].map((v) => h("label", {}, h("input", { type: "radio", name: `sus${i}`, value: String(v), required: true }), String(v)))))));
  $("#btn-sus").addEventListener("click", () => { $("#modal-sus").hidden = false; list.querySelector("input").focus(); });
  $("#sus-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const answers = SUS_ITEMS.map((_, i) => { const c = e.target.querySelector(`input[name="sus${i}"]:checked`); return c ? Number(c.value) : null; });
    if (answers.includes(null)) { $("#sus-result").textContent = "Please answer all ten statements."; return; }
    try {
      const r = await api.sus({ session_id: state.sessionId, answers });
      $("#sus-result").textContent = `Thank you. SUS score: ${r.score}.`;
    } catch (err) { $("#sus-result").textContent = err.message; }
  });
}

boot();
