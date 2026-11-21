# The template library: how to add or approve a template

The recommendations come from `library/templates.jsonl`, a curated library of predefined sentences. The questionnaire
answers choose the rules; the library supplies the wording. Nothing is generated freely.

## Files

| File | Edited by hand? | Purpose |
|---|---|---|
| `library/templates.jsonl` | yes | One template per line (schema below). The source of truth. |
| `library/questionnaire.json` | yes | Questions, options, topics, fact fields, parts, methods. |
| `library/curation/topic_map.json` | yes | Which rules each topic touches. |
| `library/curation/triggers.json` | yes | Status of every trigger phrase: banned, conditional (with a lift) or detector (topic keyword). |
| `library/curation/lifts.json` | yes | Conditions under which a conditional phrase may appear (e.g. "certified" only with a certificate). |
| `library/curation/trigger_de.json`, `examples_de.json` | yes | German equivalents for "Don't say" and for checking German text. |
| `library/topic_rules.json` | generated | Topic-to-rule mapping for review. |
| `library/dont_say.jsonl` | generated | The "Don't say" list (triggers, `fix.avoid`, bad examples). |
| `library/COVERAGE.md` | generated | Coverage per rule and the result of every hard check. |
| `library/REVIEW.csv` | generated | One row per template for review and approval. |
| `library/drafts/templates_draft.jsonl` | generated (`draft`) | Mechanical drafts from `fix.templates` and `examples[].better`. |

After any change run:

```bash
uv run python scripts/build_library.py
```

The build fails (exit code 1) and lists the problem if any hard check fails.

## Template schema

```json
{"template_id": "RC-PART-01", "topic": "recycled_content", "kind": "claim",
 "text_en": "The [component] contains [X] % recycled [material] by weight, certified to [scheme], certificate [ID].",
 "text_de": "Bestandteil [component]: [X] Gewichtsprozent [material] aus Recycling, zertifiziert nach [scheme], Zertifikat [ID].",
 "de_reviewed": false, "approved": false, "specificity": 3,
 "slots": [{"name": "X", "type": "percent", "source": "fact_field", "unit": "%"}, ...],
 "requires": {"audience": ["B2C","B2B"], "channels": [...], "product_domains": ["ALL"], "not_domains": ["PACKAGING"],
              "evidence_types": ["third_party_certificate"], "scope": ["part"], "comparison": ["none"]},
 "rule_ids": ["FP04","P02","M03","E01"], "satisfies": ["P04"], "when": {},
 "applies_from": null, "valid_until": null, "origin": "rule:FP04 fix.templates[0]", "notes": ""}
```

- **Placeholders** are `[Name]`. Each needs a slot. `source` is `fact_field` (a structured fact from question 6),
  `answer` (`component`, `excluded`, `method`, `year`, `comparator`) or `manual` (stays a placeholder to complete after
  copying, e.g. `[URL]`, `[verifier]`). Slot types: `percent`, `number`, `year`, `date`, `id`, `choice`, `manual`.
  There is no free-text slot.
- **kind**: `claim`, `cautious` (no figures, safe without evidence), `legal_neutral` (a legal requirement in neutral
  wording, "As required by law for all …"), `official_info` (official label or data), `financing_statement`, or
  `mandatory_statement` (topic `_mandatory`: appended to every sentence that fits, e.g. the biocide safe-use sentence).
- **specificity** 1–3 drives the dots on the proof slip and the ranking.
- **rule_ids**: all must apply to the ticket (rules that only fail on audience are simply not cited).
- **satisfies**: prohibited rules whose trigger words the text contains *and* whose lift the requirements imply.
- **when**: extra conditions such as `{"method": ["ppwr_adopted"]}` or `{"substance": ["antimicrobial"]}`.
- **applies_from**: required when a linked rule applies later; before that date the template only appears as a
  future note.

## Hard checks (all must pass)

1. Every template links to a rule; all linked rules' basis quotes are found word for word; no future-law rule.
2. Placeholders are well formed, each has a slot, and English and German use the same ones.
3. No banned trigger; conditional triggers only where the lift holds (prohibited rules must be in `satisfies`).
4. No wording from a linked rule's `fix.avoid`.
5. Legal requirements only in neutral wording (P05, EE01, DT01, CS02, WD01), without advantage words.
6. A figure or a certificate requires evidence other than "None yet".
7. Future `applies_from` dates are carried.
8. Coverage: every prohibited, case-by-case or evidence rule routed by ECLASS or claim object is covered.
9. A template offered for one part names `[component]`; one offered for one site names `[site]`.

The engine runs the same checks again on every filled sentence and drops any that fail.

## Add a template

1. Optionally run `uv run python scripts/build_library.py draft` and start from a draft line.
2. Add one JSON line to `library/templates.jsonl`. Reuse placeholder names from the topic's fact fields in
   `questionnaire.json`; add a fact field there if needed.
3. Write the German text with the same placeholders, and leave `de_reviewed: false`. If `text_de` is empty and the
   local model is available, the build drafts it (also `de_reviewed: false`).
4. Run the build and fix what it reports. Run `uv run pytest`.

## Approve templates and German wording

1. Open `library/REVIEW.csv` in a spreadsheet program.
2. For each row set `approved` to `yes` when the template is fine, and `de_reviewed` to `yes` when the German wording
   is correct. You may correct `text_de` directly (keep the placeholders) and write a `reviewer_comment`.
3. Save as CSV (UTF-8) and run:

```bash
uv run python scripts/build_library.py approve library/REVIEW.csv
```

The app shows "German wording not yet reviewed" on German proofs until `de_reviewed` is `yes`. The library hash
changes with every edit and is stored with every saved result, so results can be traced to the library version.
