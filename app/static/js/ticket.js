// The printer's job ticket: one question at a time, answered fields collapse into stamps.
import { h, $, clear, reducedMotion } from "./dom.js";
import { api } from "./api.js";
import { STEPS, state, labelOf, cleanAnswers, today } from "./state.js";

let onComplete = () => {};
let landing = null;          // step whose stamp should animate
let routeSeq = 0;

const SHORT = {
  product: "Product", audience: "Audience", channel: "Channel", topic: "Message", scope: "Covers",
  evidence: "Evidence", comparison: "Comparison", timing: "Timing", output: "Language and tone",
};

export function initTicket(opts) {
  onComplete = opts.onComplete;
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Backspace" || e.altKey || e.ctrlKey || e.metaKey) return;
    const t = e.target;
    const typing = t && (t.tagName === "TEXTAREA" || t.tagName === "SELECT" || (t.tagName === "INPUT" && t.value !== ""));
    if (typing || (t && t.closest && t.closest(".drawer, .modal, .proof"))) return;
    if (!t.closest || !t.closest("#ticket")) {
      if (t !== document.body) return;
    }
    const prev = previousStep(state.current);
    if (prev) { e.preventDefault(); go(prev, { back: true }); }
  });
}

// ---- flow -------------------------------------------------------------------------------
function q(id) { return state.q.questions.find((x) => x.id === id); }

function isVisible(step) {
  if (step === "comparison") return Boolean(state.route && state.route.comparable);
  return true;
}

export function isAnswered(step) {
  const a = state.answers;
  const r = state.route || {};
  switch (step) {
    case "product": return Boolean(a.segment) && (!(r.refinements || []).length || Boolean(a.product_type));
    case "audience": return Boolean(a.audience);
    case "channel": return Boolean(a.channel);
    case "topic": return Boolean(a.topic);
    case "scope": return Boolean(a.scope) && (a.scope !== "part" || Boolean(a.part)) && state.confirmed.has("scope");
    case "evidence": return Boolean(a.evidence) && state.confirmed.has("evidence");
    case "comparison": return state.confirmed.has("comparison");
    case "timing": return state.confirmed.has("timing");
    case "output": return state.confirmed.has("output");
    default: return false;
  }
}

function visibleSteps() { return STEPS.filter(isVisible); }
function previousStep(step) { const v = visibleSteps(); const i = v.indexOf(step); return i > 0 ? v[i - 1] : null; }
function firstOpen() { return visibleSteps().find((s) => !isAnswered(s)) || null; }

export function go(step, { back = false } = {}) {
  recordTime();
  if (back) state.usability.backSteps += 1;
  state.current = step;
  renderTicket({ focus: true });
}

function recordTime() {
  const now = performance.now();
  const k = state.current;
  state.usability.times[k] = Math.round((state.usability.times[k] || 0) + (now - state.usability.shownAt));
  state.usability.shownAt = now;
}

async function advance() {
  await refreshRoute();
  const next = firstOpen();
  if (next) { go(next); return; }
  recordTime();
  state.current = null;
  renderTicket();
  onComplete();
}

export async function answer(step, patch, { advanceAfter = true, confirm = false } = {}) {
  Object.assign(state.answers, patch);
  if (confirm) state.confirmed.add(step);
  landing = step;
  if (advanceAfter) await advance();
  else { await refreshRoute(); renderTicket({ focus: false }); }
}

// Prune answers that no longer fit after an earlier answer changed.
function prune() {
  const a = state.answers, r = state.route;
  if (!r) return;
  const ids = (xs) => (xs || []).map((x) => (typeof x === "string" ? x : x.id));
  if (a.product_type && !ids(r.refinements).includes(a.product_type)) { delete a.product_type; }
  if (a.topic && !ids(r.topics).includes(a.topic)) { delete a.topic; delete a.scope; state.confirmed.delete("scope"); }
  if (a.scope && r.scopes.length && !r.scopes.includes(a.scope)) { delete a.scope; state.confirmed.delete("scope"); }
  const parts = ids(r.parts);
  if (a.part && !parts.includes(a.part)) { delete a.part; state.confirmed.delete("scope"); }
  if (a.excluded && !parts.includes(a.excluded)) delete a.excluded;
  if (a.evidence && r.evidence.length && !r.evidence.includes(a.evidence)) { delete a.evidence; state.confirmed.delete("evidence"); }
  if (a.method && !ids(r.methods).includes(a.method)) delete a.method;
  const fields = new Set((r.fact_fields || []).map((f) => f.name));
  for (const k of Object.keys(a.facts)) if (!fields.has(k)) delete a.facts[k];
  if (!r.comparable) { a.comparison = "none"; }
}

export async function refreshRoute() {
  const seq = ++routeSeq;
  const r = await api.route(cleanAnswers());
  if (seq !== routeSeq) return;
  state.route = r;
  const before = JSON.stringify(state.answers);
  prune();
  if (JSON.stringify(state.answers) !== before) {
    state.route = await api.route(cleanAnswers());
  }
  renderTypecase();
}

// ---- type case: routed regulations as slugs --------------------------------------------------
const MARK = { prohibited: "P", case_by_case: "C", evidence: "E", info: "i", gate: "G", future: "F" };
export function renderTypecase() {
  const ul = $("#typecase");
  clear(ul);
  const rules = (state.route && state.route.rules) || [];
  const order = { product: 0, topic: 1, general: 2 };
  const shown = [...rules].sort((x, y) => order[x.origin] - order[y.origin]);
  for (const r of shown) {
    const isNew = !state.knownRules.has(r.rule_id);
    ul.appendChild(h("li", {},
      h("span", { class: `slug slug--${r.severity}${isNew && !reducedMotion() ? " is-new" : ""}`, title: `${r.rule_id}: ${r.title} (${r.severity.replace(/_/g, " ")})`,
        "data-mark": MARK[r.severity] || "·" }, r.rule_id)));
  }
  for (const rid of (state.route && state.route.future_dated_rules) || []) {
    ul.appendChild(h("li", {}, h("span", { class: "slug slug--future", title: `${rid}: applies later (future note only)`, "data-mark": "F" }, rid)));
  }
  state.knownRules = new Set(shown.map((r) => r.rule_id));
  $("#typecase-count").textContent = `${shown.length} rules${state.route && state.route.manual_review ? " · manual review" : ""}`;
}

// ---- rendering --------------------------------------------------------------------------------
export function renderTicket({ focus = false } = {}) {
  const ol = $("#ticket-fields");
  clear(ol);
  const steps = visibleSteps();
  steps.forEach((step, i) => {
    const active = step === state.current;
    const done = !active && isAnswered(step);
    const li = h("li", { class: `tf ${active ? "tf--active" : done ? "tf--done" : "tf--pending"}`, "data-step": step },
      h("span", { class: "tf__num", "aria-hidden": "true" }, String(i + 1)),
      h("span", { class: "tf__label" }, SHORT[step]));
    if (active) li.appendChild(renderQuestion(step));
    else if (done) li.appendChild(stampFor(step));
    ol.appendChild(li);
  });
  $("#btn-dup").disabled = !state.result;
  if (focus) {
    const target = ol.querySelector(".tf--active [data-autofocus]") || ol.querySelector(".tf--active .choices");
    if (target) target.focus({ preventScroll: false });
  }
  landing = null;
}

function stampFor(step) {
  const a = state.answers, Q = state.q, r = state.route || {};
  let main = "", sub = "";
  switch (step) {
    case "product": {
      const s = state.segments.find((x) => x.id === a.segment);
      main = s ? (s.segment_name || s.label_en) : a.segment;
      if (a.product_type) sub = labelOf(r.refinements, a.product_type);
      break;
    }
    case "audience": main = labelOf(Q.audience, a.audience);
      if (a.audience === "business" && (r.audiences || []).includes("B2C")) sub = "public: counts as consumers";
      break;
    case "channel": main = labelOf(Q.channel, a.channel); break;
    case "topic": main = Q.topics[a.topic] ? Q.topics[a.topic].label_en : a.topic; break;
    case "scope": main = labelOf(Q.scope, a.scope);
      if (a.part) sub = labelOf(r.parts, a.part);
      if (a.excluded) sub += ` · not: ${labelOf(r.parts, a.excluded)}`;
      break;
    case "evidence": main = labelOf(Q.evidence, a.evidence);
      if (a.method) sub = labelOf(r.methods, a.method);
      if (a.reference_year) sub += ` · ${a.reference_year}`;
      { const n = Object.keys(a.facts || {}).length; if (n) sub += ` · ${n} fact${n > 1 ? "s" : ""}`; }
      break;
    case "comparison": main = labelOf(Q.comparison, a.comparison || "none"); break;
    case "timing": main = a.use_date || today(); sub = `on market before: ${labelOf(Q.on_market_before, a.on_market_before || "unknown")}`; break;
    case "output": main = `${labelOf(Q.language, a.language)} · ${labelOf(Q.tone, a.tone)}`; break;
  }
  const btn = h("button", { type: "button", class: `stamp${landing === step && !reducedMotion() ? " is-landing" : ""}`,
    "aria-label": `${SHORT[step]}: ${main}${sub ? ", " + sub : ""}. Change`, onclick: () => go(step, { back: true }) },
    h("span", {}, main), sub ? h("span", { class: "stamp__sub" }, sub) : null);
  return btn;
}

function questionShell(step, ...children) {
  const qq = q(step);
  return h("div", { class: `q${reducedMotion() ? "" : " is-entering"}` },
    h("h2", { class: "q__prompt", id: `q-${step}` }, qq.prompt_en),
    qq.help_en ? h("p", { class: "q__help" }, qq.help_en) : null,
    ...children);
}

function backRow(step, ...right) {
  const prev = previousStep(step);
  return h("div", { class: "q__actions" },
    prev ? h("button", { type: "button", class: "btn btn--small", onclick: () => go(prev, { back: true }) }, "← Back") : h("span"),
    h("div", { class: "row" }, ...right));
}

// ---- listbox with keyboard support -----------------------------------------------------------
let lbCount = 0;
function listbox({ options, selected, onPick, labelledby, controller }) {
  const id = `lb${++lbCount}`;
  const ul = h("ul", { class: "choices", role: "listbox", id, tabindex: controller ? "-1" : "0", "aria-labelledby": labelledby, "data-autofocus": controller ? null : "" });
  let items = [], cursor = -1, current = options;

  function render(opts) {
    current = opts;
    clear(ul);
    items = opts.map((o, i) => {
      const li = h("li", { class: "choice", role: "option", id: `${id}-${i}`, "aria-selected": o.id === selected ? "true" : "false",
        onclick: () => onPick(o.id), onmousemove: () => setCursor(i, false) },
        h("span", { class: "choice__key", "aria-hidden": "true" }, String(i + 1).padStart(2, "0")),
        h("span", {}, o.label, o.hint ? h("span", { class: "choice__hint" }, o.hint) : null));
      return li;
    });
    items.forEach((li) => ul.appendChild(li));
    const si = opts.findIndex((o) => o.id === selected);
    setCursor(si >= 0 ? si : (opts.length ? 0 : -1), false);
  }
  function setCursor(i, scroll = true) {
    if (cursor >= 0 && items[cursor]) items[cursor].classList.remove("is-cursor");
    cursor = i;
    const host = controller || ul;
    if (i >= 0 && items[i]) {
      items[i].classList.add("is-cursor");
      host.setAttribute("aria-activedescendant", items[i].id);
      if (scroll) items[i].scrollIntoView({ block: "nearest" });
    } else host.removeAttribute("aria-activedescendant");
  }
  function onKey(e) {
    if (e.key === "ArrowDown") { e.preventDefault(); setCursor(Math.min(items.length - 1, cursor + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCursor(Math.max(0, cursor - 1)); }
    else if (e.key === "Home") { e.preventDefault(); setCursor(0); }
    else if (e.key === "End") { e.preventDefault(); setCursor(items.length - 1); }
    else if (e.key === "Enter" || (e.key === " " && !controller)) {
      if (cursor >= 0 && current[cursor]) { e.preventDefault(); onPick(current[cursor].id); }
    }
  }
  (controller || ul).addEventListener("keydown", onKey);
  render(options);
  return { el: ul, render, focus: () => (controller || ul).focus() };
}

const opt = (list, lang = "en") => (list || []).map((o) => ({ id: o.id, label: lang === "de" ? o.label_de : o.label_en }));

// ---- the nine questions ------------------------------------------------------------------------
function renderQuestion(step) {
  switch (step) {
    case "product": return qProduct();
    case "audience": return qSimple("audience", opt(state.q.audience), state.answers.audience, (v) => answer("audience", { audience: v }));
    case "channel": return qSimple("channel", opt(state.q.channel), state.answers.channel, (v) => answer("channel", { channel: v }));
    case "topic": return qSimple("topic", (state.route.topics || []).map((t) => ({ id: t.id, label: t.label_en })), state.answers.topic,
      (v) => { if (v !== state.answers.topic) { delete state.answers.scope; state.confirmed.delete("scope"); delete state.answers.method; state.confirmed.delete("evidence"); } answer("topic", { topic: v }); });
    case "scope": return qScope();
    case "evidence": return qEvidence();
    case "comparison": return qSimple("comparison", opt(state.q.comparison), state.answers.comparison || "none",
      (v) => answer("comparison", { comparison: v }, { confirm: true }));
    case "timing": return qTiming();
    case "output": return qOutput();
  }
  return h("div");
}

function qSimple(step, options, selected, onPick, extra = null) {
  const lb = listbox({ options, selected, onPick, labelledby: `q-${step}` });
  return questionShell(step, extra, lb.el, backRow(step));
}

function qProduct() {
  const a = state.answers;
  const refinements = (state.route && state.route.refinements) || [];
  if (a.segment && refinements.length && !a.product_type) {
    const seg = state.segments.find((s) => s.id === a.segment);
    const lb = listbox({ options: opt(refinements), selected: a.product_type, labelledby: "q-product-type",
      onPick: (v) => answer("product", { product_type: v }) });
    return h("div", { class: `q${reducedMotion() ? "" : " is-entering"}` },
      h("h2", { class: "q__prompt", id: "q-product-type" }, "Which kind of product is it?"),
      h("p", { class: "q__help" }, seg && seg.note ? `${seg.segment_name}: ${seg.note}.` : "The product rules depend on the kind of product."),
      lb.el,
      h("div", { class: "q__actions" }, h("button", { type: "button", class: "btn btn--small",
        onclick: () => { delete a.segment; delete a.product_type; renderTicket({ focus: true }); } }, "← Other segment")));
  }
  const input = h("input", { class: "search", type: "search", role: "combobox", "aria-autocomplete": "list", "aria-expanded": "true",
    placeholder: "Search, e.g. textile", "aria-labelledby": "q-product", "data-autofocus": "" });
  const all = state.segments.map((s) => ({ id: s.id, label: s.label_en, hint: s.manual_review ? "Routes to manual review" : (s.note || null) }));
  const lb = listbox({ options: all, selected: a.segment, labelledby: "q-product", controller: input,
    onPick: (v) => { if (v !== a.segment) delete a.product_type; answer("product", { segment: v }); } });
  input.setAttribute("aria-controls", lb.el.id);
  input.addEventListener("input", () => {
    const t = input.value.trim().toLowerCase();
    lb.render(t ? all.filter((o) => o.label.toLowerCase().includes(t) || (o.hint || "").toLowerCase().includes(t)) : all);
  });
  return questionShell("product", input, lb.el, h("div", { class: "q__actions" }, h("span")));
}

function qScope() {
  const a = state.answers, r = state.route;
  const scopes = (r.scopes || []).map((id) => ({ id, label: labelOf(state.q.scope, id) }));
  const parts = opt(r.parts);
  const body = [];
  if (!state._scopeStage) state._scopeStage = (a.scope && !["site", "company"].includes(a.scope)) ? "parts" : "scope";
  if (state._scopeStage === "scope") {
    const lb = listbox({ options: scopes, selected: a.scope, labelledby: "q-scope", onPick: (v) => {
      state.answers.scope = v;
      if (v !== "part" && v !== "packaging" && v !== "whole_product") { delete a.part; delete a.excluded; }
      if (v === "site" || v === "company") { state._scopeStage = null; answer("scope", { scope: v }, { confirm: true }); return; }
      state._scopeStage = "parts"; renderTicket({ focus: true });
    } });
    body.push(lb.el);
    return questionShell("scope", ...body, backRow("scope"));
  }
  // parts stage
  const needPart = a.scope === "part";
  const partLabel = needPart ? "Which part?" : (a.scope === "packaging" ? "Which packaging part? (optional)" : "Name a part? (optional)");
  const partSel = h("select", { "aria-label": partLabel, "data-autofocus": "" },
    h("option", { value: "" }, needPart ? "Choose a part" : "Whole unit"), ...parts.map((p) => h("option", { value: p.id, selected: p.id === a.part }, p.label)));
  const exclSel = h("select", { "aria-label": "Part not included (optional)" },
    h("option", { value: "" }, "Nothing excluded"), ...parts.map((p) => h("option", { value: p.id, selected: p.id === a.excluded }, p.label)));
  const err = h("p", { class: "fact__err", role: "alert" });
  const confirm = () => {
    if (needPart && !partSel.value) { err.textContent = "Choose the part the claim covers."; partSel.focus(); return; }
    if (partSel.value && partSel.value === exclSel.value) { err.textContent = "The excluded part cannot be the covered part."; return; }
    state._scopeStage = null;
    const patch = { part: partSel.value || undefined, excluded: exclSel.value || undefined };
    if (!patch.part) delete a.part;
    if (!patch.excluded) delete a.excluded;
    answer("scope", Object.fromEntries(Object.entries(patch).filter(([, v]) => v)), { confirm: true });
  };
  [partSel, exclSel].forEach((s) => s.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); confirm(); } }));
  return questionShell("scope",
    h("p", { class: "q__sub" }, `Covers: ${labelOf(state.q.scope, a.scope)}`),
    h("div", { class: "facts" },
      h("div", { class: "fact" }, h("label", {}, partLabel), partSel),
      h("div", { class: "fact" }, h("label", {}, "Part not included ", h("span", { class: "optional" }, "(optional)")), exclSel)),
    err,
    h("div", { class: "q__actions" },
      h("button", { type: "button", class: "btn btn--small", onclick: () => { state._scopeStage = "scope"; renderTicket({ focus: true }); } }, "← Scope"),
      h("button", { type: "button", class: "btn", onclick: confirm }, "Stamp")));
}

function factInput(f, value) {
  const pats = state.q.patterns;
  if (f.type === "choice") {
    const list = state.q.option_lists[f.options] || [];
    return h("select", { name: f.name, id: `fact-${f.name}` }, h("option", { value: "" }, "—"),
      ...list.map((o) => h("option", { value: o.id, selected: o.id === value }, o.label_en)));
  }
  if (f.type === "date") return h("input", { type: "date", name: f.name, id: `fact-${f.name}`, value: value || "" });
  const attrs = { type: "text", name: f.name, id: `fact-${f.name}`, value: value || "", autocomplete: "off", spellcheck: "false",
    pattern: pats[f.type] ? pats[f.type].replace(/^\^|\$$/g, "") : null, maxlength: f.type === "id" ? 40 : 12 };
  if (f.type === "percent" || f.type === "number") attrs.inputmode = "decimal";
  if (f.type === "year") { attrs.inputmode = "numeric"; attrs.maxlength = 4; attrs.placeholder = "YYYY"; }
  return h("input", attrs);
}

function qEvidence() {
  const a = state.answers, r = state.route;
  const evid = (r.evidence || []).map((id) => ({ id, label: labelOf(state.q.evidence, id) }));
  const note = r.topic_note ? h("p", { class: "q__note" }, r.topic_note,
    a.topic === "general_benefit" ? h("span", {}, " ", h("button", { type: "button", class: "btn btn--small", onclick: () => go("topic", { back: true }) }, "Switch topic")) : null) : null;
  if (!a.evidence || state._evStage !== "details") {
    const lb = listbox({ options: evid, selected: a.evidence, labelledby: "q-evidence", onPick: (v) => {
      a.evidence = v;
      if (v === "none_yet") { a.facts = Object.fromEntries(Object.entries(a.facts).filter(([k]) => !isFigureField(k))); }
      state._evStage = "details"; renderTicket({ focus: true });
    } });
    return questionShell("evidence", note, lb.el, backRow("evidence"));
  }
  // details: method, year, facts
  const methods = r.methods || [];
  const method = methods.length ? h("select", { id: "ev-method", "data-autofocus": "" }, h("option", { value: "" }, "Not specified"),
    ...methods.map((m) => h("option", { value: m.id, selected: m.id === a.method }, m.label_en))) : null;
  const year = h("input", { type: "text", id: "ev-year", inputmode: "numeric", maxlength: 4, placeholder: "YYYY", value: a.reference_year || "",
    pattern: "(19[9][0-9]|20[0-9]{2}|2100)", "data-autofocus": methods.length ? null : "" });
  const none = a.evidence === "none_yet";
  const fields = (r.fact_fields || []).filter((f) => !(none && isFigureFieldDef(f)));
  const inputs = fields.map((f) => {
    const inp = factInput(f, a.facts[f.name]);
    const errEl = h("span", { class: "fact__err", id: `err-${f.name}`, "aria-live": "polite" });
    inp.setAttribute("aria-describedby", errEl.id);
    return { f, inp, errEl, el: h("div", { class: "fact" }, h("label", { for: inp.id }, f.label_en),
      h("div", { class: "fact__row" }, inp, f.unit ? h("span", { class: "fact__unit" }, f.unit) : null), errEl) };
  });
  const confirm = () => {
    let ok = true;
    const facts = {};
    for (const { f, inp, errEl } of inputs) {
      const v = (inp.value || "").trim();
      errEl.textContent = "";
      if (!v) continue;
      if (f.type !== "choice" && f.type !== "date" && state.q.patterns[f.type] && !new RegExp(state.q.patterns[f.type]).test(v)) {
        errEl.textContent = { percent: "Use a number from 0 to 100, e.g. 60 or 60.5", number: "Use digits only, e.g. 12.5", year: "Use a year such as 2025", id: "Letters, digits, '.', '/' and '-' only" }[f.type] || "Check the format";
        ok = false; continue;
      }
      facts[f.name] = v;
    }
    const y = year.value.trim();
    if (y && !/^(19[9][0-9]|20[0-9]{2}|2100)$/.test(y)) { ok = false; year.setAttribute("aria-invalid", "true"); }
    if (!ok) return;
    state._evStage = null;
    a.facts = facts;
    const patch = { method: method && method.value ? method.value : undefined, reference_year: y || undefined };
    if (!patch.method) delete a.method;
    if (!patch.reference_year) delete a.reference_year;
    answer("evidence", Object.fromEntries(Object.entries(patch).filter(([, v]) => v)), { confirm: true });
  };
  const wrap = h("div", { class: "facts" });
  if (method) wrap.appendChild(h("div", { class: "fact" }, h("label", { for: "ev-method" }, "Method or standard"), method));
  wrap.appendChild(h("div", { class: "fact" }, h("label", { for: "ev-year" }, "Reference period or year ", h("span", { class: "optional" }, "(optional)")), year));
  if (inputs.length) wrap.appendChild(h("p", { class: "q__sub" }, none ? "Facts (no figures without evidence)" : "Facts (optional — empty facts stay as placeholders)"));
  inputs.forEach((x) => wrap.appendChild(x.el));
  wrap.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName !== "SELECT") { e.preventDefault(); confirm(); } });
  return questionShell("evidence", note,
    h("p", { class: "q__sub" }, `Evidence: ${labelOf(state.q.evidence, a.evidence)}`),
    none ? h("p", { class: "q__note" }, "No sentence with a figure or a certificate will be set before evidence exists. You will see what to obtain first.") : null,
    wrap,
    h("div", { class: "q__actions" },
      h("button", { type: "button", class: "btn btn--small", onclick: () => { state._evStage = null; delete a.evidence; renderTicket({ focus: true }); } }, "← Evidence type"),
      h("button", { type: "button", class: "btn", onclick: confirm }, "Stamp")));
}

function isFigureFieldDef(f) { return f.type === "percent" || f.type === "number" || f.name === "ID"; }
function isFigureField(name) {
  const f = ((state.route && state.route.fact_fields) || []).find((x) => x.name === name);
  return f ? isFigureFieldDef(f) : false;
}

function qTiming() {
  const a = state.answers;
  const date = h("input", { type: "date", id: "t-date", value: a.use_date || today(), "data-autofocus": "" });
  const lb = listbox({ options: opt(state.q.on_market_before), selected: a.on_market_before || "unknown", labelledby: "t-omb",
    onPick: (v) => { if (!date.value) return; answer("timing", { use_date: date.value, on_market_before: v }, { confirm: true }); } });
  return questionShell("timing",
    h("div", { class: "fact" }, h("label", { for: "t-date" }, "Date of use"), date),
    h("p", { class: "q__sub", id: "t-omb" }, "On the market before 27 September 2026?"),
    lb.el, backRow("timing"));
}

function qOutput() {
  const a = state.answers;
  let lang = a.language || "en";
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Output language" },
    ...state.q.language.map((l) => h("button", { type: "button", "aria-pressed": l.id === lang ? "true" : "false", "data-lang": l.id,
      onclick: (e) => { lang = l.id; seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.lang === lang ? "true" : "false")); } }, l.label_en)));
  const lb = listbox({ options: opt(state.q.tone).map((o) => ({ ...o, hint: o.id === "factual" ? "Template wording" : "Needs the local AI; otherwise the template wording is kept" })),
    selected: a.tone || "factual", labelledby: "o-tone",
    onPick: (v) => answer("output", { language: lang, tone: v }, { confirm: true }) });
  lb.el.setAttribute("data-autofocus", "");
  return questionShell("output",
    h("p", { class: "q__sub" }, "Language"), seg,
    h("p", { class: "q__sub", id: "o-tone" }, "Tone — choose to set the type"), lb.el, backRow("output"));
}

export function resetTicketStages() { state._scopeStage = null; state._evStage = null; }
