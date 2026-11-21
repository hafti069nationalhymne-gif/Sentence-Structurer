// The composing area: recommended sentences set in type as proof slips, with the law in the margin.
import { h, $, clear, toast, reducedMotion } from "./dom.js";
import { api } from "./api.js";
import { state, cleanAnswers, labelOf } from "./state.js";

const DS_LIMIT = 12;
const STATUS = { prohibited: "prohibited", case_by_case: "case by case", evidence: "evidence", info: "info", gate: "gate" };

export function renderEmpty() {
  const stage = clear($("#stage"));
  stage.appendChild(h("div", { class: "stick" },
    h("p", { class: "stick__title" }, "The composing stick is empty"),
    h("p", { class: "stick__text" }, "Answer the job ticket on the left. When the last answer is stamped, the recommended sentences are set here in type and pulled as proofs, with the law noted in the margin."),
    h("p", { class: "stick__press" }, "Research prototype · Not legal advice · Human review required")));
}

export function renderSetting() {
  const stage = clear($("#stage"));
  stage.appendChild(h("div", { class: "stick", "aria-busy": "true" },
    h("p", { class: "stick__title" }, "Setting the type…"),
    h("p", { class: "stick__text" }, "Checking every sentence against the rules for this ticket.")));
}

export function renderError(msg) {
  const stage = clear($("#stage"));
  stage.appendChild(h("div", { class: "stick" }, h("p", { class: "stick__title" }, "The press jammed"), h("p", { class: "stick__text" }, msg)));
}

// ---- result ---------------------------------------------------------------------------
export function renderResult(res, { animate = true } = {}) {
  const anim = animate && !reducedMotion();
  const stage = clear($("#stage"));
  const ctx = res.context || {};
  stage.appendChild(h("div", { class: "result-head" },
    h("h2", {}, res.recommendations.length ? `${res.recommendations.length} proof${res.recommendations.length > 1 ? "s" : ""} pulled` : "No proof pulled"),
    h("span", { class: "result-head__meta" },
      `${ctx.topic_label || ""} · ${res.run.mode === "ai" ? `AI (${res.run.chat_model})` : "template mode"} · ${res.run.duration_ms} ms`)));
  if (res.notes && res.notes.length) {
    stage.appendChild(h("ul", { class: "notes" }, ...res.notes.map((n) => h("li", { "data-kind": n.kind },
      n.text, n.rule_id ? h("span", { class: "rule-ref" }, ` (${n.rule_id})`) : null))));
  }
  const proofs = h("div", { class: "proofs" });
  res.recommendations.forEach((rec, i) => proofs.appendChild(proofSlip(rec, i, anim, res)));
  if (!res.recommendations.length) {
    proofs.appendChild(h("div", { class: "stick" },
      h("p", { class: "stick__title" }, "No sentence fits yet"),
      h("p", { class: "stick__text" }, res.what_to_obtain && res.what_to_obtain.length
        ? "Nothing can be set safely with these answers. Obtain the items listed beside this, then run the ticket again."
        : "Change an answer on the ticket — scope, evidence or method — and the type will be set again.")));
  }
  const side = h("div", { class: "side" });
  if (res.what_to_obtain && res.what_to_obtain.length) side.appendChild(obtainCard(res.what_to_obtain));
  side.appendChild(dontSayProof(res.dont_say, anim));
  if (res.future_requirements && res.future_requirements.length) side.appendChild(futureCard(res.future_requirements));
  stage.appendChild(h("div", { class: "press" }, proofs, side));
  stage.appendChild(h("p", { class: "disclaimer" }, res.disclaimer));
  if (anim) $("#composer").scrollIntoView({ behavior: "smooth", block: "start" });
}

function specDots(n) {
  return h("span", { class: "spec", title: `Specificity ${n} of 3`, "aria-label": `Specificity ${n} of 3` },
    ...[1, 2, 3].map((k) => h("span", { class: `spec__dot${k <= n ? " is-on" : ""}`, "aria-hidden": "true" })));
}

function proofSlip(rec, i, anim, res) {
  const slip = h("article", { class: `proof${anim ? " is-setting" : ""}`, "aria-label": `Proof ${i + 1}`, style: anim ? { "animation-delay": `${i * 260}ms` } : {} });
  slip._rec = rec;
  slip._values = {};
  slip._lang = rec.language;
  slip._tone = state.answers.tone || "factual";
  slip._index = i;
  fillSlip(slip, rec, anim ? i * 260 + 200 : null, res);
  return slip;
}

function fillSlip(slip, rec, animDelay, res) {
  clear(slip);
  const tags = [];
  if (rec.safest) tags.push(h("span", { class: "tag tag--safe" }, "Safest option"));
  if (rec.ai_adjusted) tags.push(h("span", { class: "tag tag--ai" }, `AI: ${rec.ai_parts.join(", ")}`));
  for (const t of rec.tags || []) tags.push(h("span", { class: "tag" }, t));
  slip.appendChild(h("header", { class: "proof__head" },
    h("span", {}, h("span", { class: "proof__no" }, `Proof ${(slip._index || 0) + 1}`), ` · ${rec.template_id}`),
    h("span", { class: "row" }, ...tags, specDots(rec.specificity))));

  const main = h("div", { class: "proof__main" });
  main.appendChild(sentenceEl(rec, slip, animDelay));
  main.appendChild(h("p", { class: "fits" }, rec.status_line));
  main.appendChild(h("div", { class: "block block--why" }, h("p", { class: "block__label" }, "Why it fits"), h("p", {}, rec.why_it_fits)));
  main.appendChild(h("div", { class: "block block--verify" }, h("p", { class: "block__label" }, "Facts to verify before use"),
    h("ul", { class: "verify" }, ...rec.facts_to_verify.map((f) => h("li", {}, f)))));
  main.appendChild(actions(slip, rec));
  slip.appendChild(main);
  slip.appendChild(marginCol(rec));
  if (state.settings.review_mode) slip.appendChild(reviewBlock(rec));
  slip.appendChild(h("p", { class: "proof__quiet" }, "Research prototype. Not legal advice. Human review required."));
}

// The sentence, set word by word, with placeholder chips as the only editable fields.
function sentenceEl(rec, slip, animDelay) {
  const p = h("p", { class: `sentence${animDelay !== null && animDelay !== undefined ? " is-setting" : ""}`, lang: rec.language,
    style: animDelay != null ? { "--d": `${animDelay}ms` } : {} });
  const chips = Object.fromEntries((rec.placeholder_chips || []).map((c) => [c.name, c]));
  const parts = rec.sentence.split(/(\[[A-Za-z][A-Za-z0-9_]*\])/);
  let w = 0;
  for (const part of parts) {
    const m = part.match(/^\[([A-Za-z][A-Za-z0-9_]*)\]$/);
    if (m) {
      const chip = chips[m[1]] || { name: m[1], editable: false, label: m[1] };
      p.appendChild(chipEl(chip, slip, w++));
      continue;
    }
    for (const token of part.split(/(\s+)/)) {
      if (!token) continue;
      if (/^\s+$/.test(token)) { p.appendChild(document.createTextNode(" ")); continue; }
      p.appendChild(h("span", { class: "w", style: { "--i": String(w++) } }, token));
    }
  }
  return p;
}

function chipEl(chip, slip, i) {
  const label = chip.label || chip.name;
  if (!chip.editable) {
    return h("span", { class: "chip chip--manual w", title: `${label}: complete this after copying`, style: { "--i": String(i) }, tabindex: "0",
      "aria-label": `Placeholder ${chip.name}, complete outside the app` }, chip.name.replace(/_/g, " "));
  }
  const text = chip.name.length <= 2 ? label.toLowerCase() : chip.name.replace(/_/g, " ");
  return h("button", { type: "button", class: "chip w", style: { "--i": String(i) }, title: `Fill in: ${label}`,
    "aria-label": `Placeholder ${chip.name}: ${label}. Fill in`, onclick: (e) => openChipEditor(e.currentTarget, chip, slip) }, text);
}

function openChipEditor(btn, chip, slip) {
  const pats = state.q.patterns;
  let input;
  if (chip.options) {
    input = h("select", { "aria-label": chip.label }, h("option", { value: "" }, "—"), ...chip.options.map((o) => h("option", { value: o.id }, o.label)));
  } else {
    const typ = chip.type === "date" ? "date" : "text";
    input = h("input", { type: typ, "aria-label": chip.label, autocomplete: "off", spellcheck: "false",
      inputmode: chip.type === "percent" || chip.type === "number" || chip.type === "year" ? "decimal" : null,
      maxlength: chip.type === "id" ? 40 : 12, placeholder: chip.unit || chip.type });
  }
  const err = h("span", { class: "chip-error", role: "alert" });
  const editor = h("span", { class: "chip-editor" }, input, chip.unit ? h("span", { class: "fact__unit" }, chip.unit) : null,
    h("button", { type: "button", class: "btn btn--small", onclick: () => apply() }, "Set"),
    h("button", { type: "button", class: "btn btn--small", onclick: () => cancel() }, "Cancel"), err);
  btn.replaceWith(editor);
  input.focus();
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); apply(); }
    if (e.key === "Escape") { e.preventDefault(); cancel(); }
  });
  function cancel() { editor.replaceWith(btn); btn.focus(); }
  async function apply() {
    const v = (input.value || "").trim();
    if (!v) { cancel(); return; }
    if (!chip.options && pats[chip.type] && chip.type !== "date" && !new RegExp(pats[chip.type]).test(v)) {
      err.textContent = { percent: "0 to 100, e.g. 60", number: "digits, e.g. 12.5", year: "a year such as 2025", id: "letters, digits, . / - only" }[chip.type] || "check the format";
      return;
    }
    const values = { ...slip._values, [chip.name]: v };
    try {
      const r = await api.revalidate({ ...cleanAnswers(), language: slip._lang }, slip._rec.template_id, values);
      if (!r.ok) {
        err.textContent = Object.values(r.errors || {}).join("; ") || "This value does not pass the checks.";
        return;
      }
      slip._values = values;
      slip._rec = { ...r.recommendation, safest: slip._rec.safest };
      fillSlip(slip, slip._rec, null);
      toast("Checked again — the sentence still fits the rules.");
    } catch (e) { err.textContent = e.message; }
  }
}

function actions(slip, rec) {
  const copyBtn = h("button", { type: "button", class: "btn", onclick: () => copy(slip) }, "Copy");
  const langSeg = h("div", { class: "seg", role: "group", "aria-label": "Language of this proof" },
    ...["en", "de"].map((l) => h("button", { type: "button", "aria-pressed": slip._lang === l ? "true" : "false",
      onclick: () => adjust(slip, { lang: l }) }, l.toUpperCase())));
  const tone = h("select", { class: "tone-select", "aria-label": "Tone of this proof", onchange: (e) => adjust(slip, { tone: e.target.value }) },
    ...state.q.tone.map((t) => h("option", { value: t.id, selected: t.id === slip._tone }, `Tone: ${t.label_en}`)));
  const srcBtn = h("button", { type: "button", class: "btn btn--small", "aria-expanded": "false", onclick: (e) => toggleSources(slip, rec, e.currentTarget) }, "Show sources");
  return h("div", { class: "proof__actions" }, copyBtn, langSeg, tone, srcBtn);
}

async function copy(slip) {
  const text = slip._rec.sentence;
  try { await navigator.clipboard.writeText(text); }
  catch {
    const ta = h("textarea", {}, text); document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } finally { ta.remove(); }
  }
  toast(slip._rec.placeholders.length ? "Copied. Remember to complete the marked placeholders." : "Copied.");
  api.event({ session_id: state.sessionId, ticket_id: state.ticketId, type: "copy", payload: { template_id: slip._rec.template_id } });
  if (state.usability.firstCopyMs === null) {
    state.usability.firstCopyMs = Math.round(performance.now() - state.usability.startedAt);
    if (state.settings.usability_mode) {
      api.usability({ session_id: state.sessionId, ticket_id: state.ticketId, question_times: state.usability.times,
        back_steps: state.usability.backSteps, time_to_first_copy_ms: state.usability.firstCopyMs }).catch(() => null);
    }
  }
}

async function adjust(slip, { lang, tone }) {
  if (lang) slip._lang = lang;
  if (tone) slip._tone = tone;
  try {
    const r = await api.adjust({ ...cleanAnswers(), language: slip._lang, tone: slip._tone }, slip._rec.template_id, slip._values);
    if (!r.ok) { toast(Object.values(r.errors || {}).join("; ") || "This change does not pass the checks."); return; }
    slip._rec = { ...r.recommendation, safest: slip._rec.safest };
    fillSlip(slip, slip._rec, reducedMotion() ? null : 0);
    if (r.message) toast(r.message);
    api.event({ session_id: state.sessionId, ticket_id: state.ticketId, type: lang ? "language" : "tone", payload: { lang, tone } });
  } catch (e) { toast(e.message); }
}

function shorten(t, n = 110) { return t && t.length > n ? t.slice(0, n - 1).trimEnd() + "…" : t; }

function marginCol(rec) {
  const col = h("aside", { class: "margin", "aria-label": "Regulations" }, h("p", { class: "margin__label" }, "Regulations"));
  const byRule = {};
  for (const g of rec.regulations) (byRule[g.rule_id] = byRule[g.rule_id] || []).push(g);
  for (const [rid, gs] of Object.entries(byRule)) {
    const g = gs[0];
    col.appendChild(h("div", { class: "cite" },
      h("div", { class: "cite__rule" }, h("span", { class: "slug", "data-mark": "§" }, rid), h("span", {}, g.rule_title)),
      h("p", { class: "cite__doc" }, `${g.doc_title} · ${g.locator}`),
      h("span", { class: "cite__status" }, `${g.jurisdiction} · ${g.legal_status}`),
      h("p", { class: "cite__quote", lang: g.language }, `“${g.quote}”`),
      g.german_counterpart ? h("p", { class: "cite__de" }, `DE: ${g.german_counterpart.provision}`) : null,
      g.caution ? h("p", { class: "cite__caution", title: g.caution }, shorten(g.caution)) : null,
      gs.length > 1 ? h("p", { class: "cite__more" }, `+${gs.length - 1} more under “Show sources”`) : null));
  }
  return col;
}

async function toggleSources(slip, rec, btn) {
  const open = slip.querySelector(".sources");
  if (open) { open.remove(); btn.setAttribute("aria-expanded", "false"); btn.textContent = "Show sources"; return; }
  btn.setAttribute("aria-expanded", "true"); btn.textContent = "Hide sources";
  const box = h("section", { class: "sources", "aria-label": "Sources" }, h("p", { class: "margin__label" }, "Full passages behind the cited rules"));
  slip.insertBefore(box, slip.querySelector(".review, .proof__quiet"));
  api.event({ session_id: state.sessionId, ticket_id: state.ticketId, type: "sources", payload: { template_id: rec.template_id } });
  for (const rid of rec.rule_ids) {
    try {
      const s = await api.sources(rid);
      box.appendChild(h("div", { class: "sources__item" },
        h("p", { class: "cite__rule" }, h("span", { class: "slug", "data-mark": "§" }, rid), ` ${s.title}`),
        h("p", { class: "hint" }, s.requirement),
        ...s.passages.slice(0, 4).map((p) => h("div", {},
          h("p", { class: "cite__doc" }, `${p.doc_title} · ${p.locator} · ${p.legal_status} · ${p.chunk_id}`),
          p.caution ? h("p", { class: "cite__caution" }, p.caution) : null,
          h("div", { class: "sources__text", lang: p.jurisdiction === "DE" ? "de" : "en" }, p.text)))));
    } catch { /* ignore */ }
  }
  // "more sources": BM25 search over the knowledge base
  const q = h("input", { type: "search", "aria-label": "Search more sources", placeholder: "Search more sources (keyword search)", maxlength: 200 });
  const results = h("div");
  const run = async () => {
    clear(results);
    if (!q.value.trim()) return;
    const r = await api.search(q.value.trim());
    for (const c of r.results) results.appendChild(h("div", { class: "sources__item" },
      h("p", { class: "cite__doc" }, `${c.doc_title} · ${c.locator} · ${c.legal_status}${c.collection === "interpretation" ? " (interpretation)" : ""}`),
      c.caution ? h("p", { class: "cite__caution" }, c.caution) : null,
      h("div", { class: "sources__text" }, c.text)));
  };
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); run(); } });
  box.appendChild(h("p", { class: "margin__label" }, "More sources"));
  box.appendChild(h("div", { class: "sources__search" }, q, h("button", { type: "button", class: "btn btn--small", onclick: run }, "Search")));
  box.appendChild(results);
}

function reviewBlock(rec) {
  const name = `fits-${rec.template_id}-${Math.random().toString(36).slice(2, 6)}`;
  const fits = h("fieldset", {}, h("legend", {}, "Fits the rules?"),
    ...["yes", "no", "unsure"].map((v) => h("label", {}, h("input", { type: "radio", name, value: v }), v)));
  const useName = name + "-use";
  const use = h("fieldset", {}, h("legend", {}, "Would you use it? (1 = no, 5 = yes)"),
    ...[1, 2, 3, 4, 5].map((v) => h("label", {}, h("input", { type: "radio", name: useName, value: String(v) }), String(v))));
  const comment = h("textarea", { maxlength: 2000, "aria-label": "Comment (stays on this computer, never sent to the model)", placeholder: "Comment (optional)" });
  const status = h("span", { class: "hint", role: "status" });
  const save = async () => {
    const f = fits.querySelector("input:checked"), u = use.querySelector("input:checked");
    try {
      await api.review({ ticket_id: state.ticketId, template_id: rec.template_id, fits: f ? f.value : null,
        would_use: u ? Number(u.value) : null, comment: comment.value || null });
      status.textContent = "Saved locally.";
    } catch (e) { status.textContent = e.message; }
  };
  return h("section", { class: "review", "aria-label": "Review" }, fits, use, comment,
    h("div", { class: "row" }, h("button", { type: "button", class: "btn btn--small", onclick: save }, "Save review"), status));
}

function dontSayProof(items, anim) {
  const box = h("section", { class: `dontsay${anim ? " is-setting" : ""}`, "aria-labelledby": "ds-title" });
  box.appendChild(h("h3", { class: "dontsay__stamp", id: "ds-title" }, "Don’t say"));
  box.appendChild(h("p", { class: "dontsay__intro" }, "Phrases to avoid for this product, audience and channel, with the reason."));
  // Group consecutive phrases of the same rule and reason: one reason, several struck phrases.
  const phrases = [];
  for (const d of items.filter((x) => x.kind !== "advice")) {
    const last = phrases[phrases.length - 1];
    if (last && last.rule_id === d.rule_id && last.reason === d.reason && last.kind === d.kind && d.kind !== "example") last.list.push(d);
    else phrases.push({ rule_id: d.rule_id, reason: d.reason, kind: d.kind, list: [d] });
  }
  const advice = items.filter((d) => d.kind === "advice");
  const ul = h("ul", { class: "ds" });
  let k = 0;
  const renderList = (n) => {
    clear(ul); k = 0;
    phrases.slice(0, n).forEach((g) => {
      const li = h("li", {});
      g.list.forEach((d, j) => {
        li.appendChild(h("span", { class: `ds__phrase${d.kind === "example" ? " ds__example" : ""}`, lang: d.phrase_language, style: { "--i": String(Math.min(k++, 18)) } },
          h("s", {}, d.kind === "example" ? `“${d.phrase}”` : d.phrase)));
        if (j < g.list.length - 1) li.appendChild(document.createTextNode(" · "));
      });
      li.appendChild(h("span", { class: "ds__rule" }, g.rule_id));
      li.appendChild(h("span", { class: "ds__reason" }, g.reason));
      ul.appendChild(li);
    });
  };
  renderList(DS_LIMIT);
  box.appendChild(ul);
  if (phrases.length > DS_LIMIT) {
    const more = h("button", { type: "button", class: "btn btn--small ds__more", "aria-expanded": "false" }, `Show all ${phrases.length} groups`);
    more.addEventListener("click", () => {
      const openNow = more.getAttribute("aria-expanded") !== "true";
      renderList(openNow ? phrases.length : DS_LIMIT);
      more.setAttribute("aria-expanded", openNow ? "true" : "false");
      more.textContent = openNow ? "Show fewer" : `Show all ${phrases.length} groups`;
    });
    box.appendChild(more);
  }
  if (advice.length) {
    box.appendChild(h("p", { class: "block__label", style: { "margin-top": "14px" } }, "Also avoid"));
    box.appendChild(h("ul", { class: "verify" }, ...advice.slice(0, 6).map((d) => h("li", {}, `${d.phrase} (${d.rule_id})`))));
  }
  return box;
}

function obtainCard(items) {
  return h("section", { class: "card card--obtain", "aria-labelledby": "obtain-title" },
    h("h3", { id: "obtain-title" }, "What to obtain first"),
    h("ol", {}, ...items.map((w) => h("li", {}, w.item, h("span", { class: "rule-ref mono-label" }, ` ${w.rule_id}`)))));
}

function futureCard(items) {
  return h("section", { class: "card card--future", "aria-labelledby": "future-title" },
    h("h3", { id: "future-title" }, "Margin notes: the future"),
    ...items.map((f) => h("div", { class: "future" },
      h("p", { class: "future__title" }, `${f.rule_id} · ${f.title}`),
      h("p", { style: { margin: "2px 0" } }, f.text),
      (f.template_previews || []).length ? h("p", { class: "hint" }, "Wording available then: ", ...f.template_previews.map((t) => h("em", {}, t.text))) : null,
      (f.positions || []).length ? h("ul", { class: "positions" }, ...f.positions.map((p) => h("li", {}, h("b", {}, p.version), p.summary))) : null)));
}


// After the template result is shown, let the AI adjust tone, language and the explanation, one proof at a time.
export async function polishWithAI() {
  const slips = Array.from(document.querySelectorAll(".proof")).filter((s) => s._rec);
  for (const slip of slips) {
    if (!slip.isConnected) return;  // a new ticket was started
    const row = slip.querySelector(".proof__head .row");
    const tag = h("span", { class: "tag tag--ai", role: "status" }, "AI polishing…");
    if (row) row.prepend(tag);
    try {
      const before = slip._rec.template_id;
      const r = await api.adjust({ ...cleanAnswers(), language: slip._lang, tone: slip._tone }, before, slip._values);
      if (slip.isConnected && r.ok && r.mode === "ai" && slip._rec.template_id === before) {
        slip._rec = { ...r.recommendation, safest: slip._rec.safest };
        fillSlip(slip, slip._rec, null);
        api.event({ session_id: state.sessionId, ticket_id: state.ticketId, type: "ai_adjust",
          payload: { template_id: before, sentence: slip._rec.sentence, ai_parts: slip._rec.ai_parts } });
      } else tag.remove();
    } catch { tag.remove(); }
  }
}
