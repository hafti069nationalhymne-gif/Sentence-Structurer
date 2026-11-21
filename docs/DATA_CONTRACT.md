# Data contract: the knowledge package

ClaimComposer reads the knowledge package in `knowledge/` as read-only data. The
loader (`app/knowledge.py`) validates every record with pydantic at start-up and
refuses to run if a record breaks this contract. Field names are used exactly as
they appear in the files.

Checked against the package on 21 November 2026: 1,166 passages, 94 rules,
323 basis quotes (all found word for word in one part of their parent passage).

## `data/chunks.jsonl` (1,166 passages)

| Field | Type | Notes |
|---|---|---|
| `chunk_id` | str | Unique. Multi-part passages end in `-p1`, `-p2`, … |
| `parent_id` | str | Shared by all parts of one provision. 71 parents have more than one part (up to 15). |
| `part` | str | `"n/m"`. Sort numerically, not as text. |
| `doc_id`, `list_id`, `doc_title`, `locator`, `heading`, `page` | | `locator` is shown to the user. |
| `jurisdiction` | `EU` \| `DE` | |
| `language` | `en` \| `de` | German law stays in German. |
| `source_type` | enum | `binding_law`, `amending_act`, `case_law`, `soft_law`, `legislative_reasoning`, `translation`, `legislative_proposal`, `negotiating_position`. Mapped to the "legal status" label in the UI. |
| `authority_rank` | int 1–6 | 1 law · 2 case law and amending acts · 3 Commission guidance · 4 legislative reasoning · 5 translation · 6 future law. |
| `collection` | enum | `current_law`, `interpretation`, `future_law`, `reference_only`. |
| `audience` | list | `B2C`, `B2B`. |
| `valid_from`, `valid_to` | ISO date or null | |
| `currency` | enum | e.g. `current`, `original_text_not_consolidated`, `adopted_not_yet_applicable`, `proposal_not_law`, `superseded`. |
| `caution` | str or null | Shown with the passage. 363 passages carry one. |
| `product_domains` | list | `ALL` or a domain such as `TEXTILE`, `PACKAGING`. |
| `text` | str | Shown to the user and searched for quotes. |
| `embed_text` | str | Not used: there is no embedding model. BM25 runs over `doc_title + locator + text`. |
| `claim_types`, `equivalent_chunks`, `linked_rules`, `relevance` | | Loaded, used only for display/search. |

## `data/rules.jsonl` (94 rules)

| Field | Notes |
|---|---|
| `rule_id`, `title`, `group` | Groups: `gate`, `blacklist`, `misleading`, `b2b`, `germany`, `evidence`, `product`, `future_watch`. |
| `severity` | `gate` (3), `prohibited` (19), `case_by_case` (40), `evidence` (20), `info` (5), `future` (7). |
| `audience` | `B2C` and/or `B2B`. Black-list rules are `B2C` only. |
| `requirement` | Plain-language requirement. Used as the deterministic "Why it fits" text. |
| `triggers` | Lower-case English phrases (some German). `E01` and `B01` are empty; `FW01` and `FW02` use `*` (every explicit claim). |
| `test`, `facts_needed`, `passes_if`, `exceptions` | `facts_needed` feeds "Facts to verify" and "What to obtain". |
| `fix.strategy`, `fix.templates`, `fix.avoid` | Templates are drafting sources. Quoted phrases in `fix.avoid` are hard-banned in linked templates. |
| `examples[]` | `{claim, finding, better, source}`. `claim` is always a **bad** example and only feeds "Don't say". `better` is a drafting source. |
| `basis[]` | `{chunk, role, quote}`. `chunk` is a **`parent_id`**; all parts are loaded. Roles: `primary`, `interpretation`, `german_law`, `case_law`, `proposal`, `parliament_position`, `council_position`. |
| `notes`, `positions` | `positions` (FW rules) hold the Commission, Parliament and Council versions, shown separately. |
| `scope.routing` | `all` (26), `eclass` (31), `claim_object` (30), `future_watch` (7). |
| `scope.product_domains`, `scope.channels` | `channels` is `any` or a list such as `label`, `packaging`, `advertising`, `website`, `technical_material`, `point_of_sale`. |
| `scope.applies_from` | ISO date or null. Set on `PK05` (2028-08-12), `DT02` (2029-09-23), `TR01` (2030-12-02), `DU01` (2026-09-27). A rule whose date is after the claim date only produces a future note. |
| `scope.claim_object` | Links claim-object rules to `claim_object_routing.csv`. |

## Routing and reference tables (CSV, UTF-8 with BOM)

| File | Columns | Use |
|---|---|---|
| `eclass_routing.csv` | `eclass_segment, segment_name, list_ids, product_rule_ids, note` | Question 1 list and product rules per segment. Segment 90 and "Not sure" route to manual review. |
| `claim_object_routing.csv` | `claim_object, rule_ids, use` | Topic rules (see `library/topic_rules.json`). |
| `concordance_eu_de.csv` | `topic, eu_provision, eu_chunk_id, german_provision, german_chunk_id, rule_id` | German counterpart shown with each EU citation. |
| `future_concordance_dfa.csv` | `rule_ids, topic, current_provision, current_chunk_id, dfa_provision, dfa_chunk_id, comparison_basis, word_similarity, change` | Digital Fairness Act notes (future only). |
| `standards_reference.csv` | `list_id, standard, title, status_checked_2026_11_18, rag_use, status_source` | Names of ISO standards as evidence routes. **Metadata only: never quoted or summarised.** |
| `source_manifest.csv` | `list_id, file, doc_id, identified_as, use, chunks, issue, sha256` | Shown in the "more sources" view as known issues. |

## Traps handled in code

- `basis[].chunk` is a `parent_id`; every part is loaded and the quote is verified against the part that contains it. The cited `chunk_id` is that part.
- `collection = future_law` passages (and the `proposal`/`*_position` basis roles) never appear as a regulation behind a recommendation. They are used only for "Possible future requirement (not law)" notes.
- `collection = reference_only` passages are never cited.
- `examples[].claim` values only feed "Don't say".
- English triggers get German equivalents (`library/trigger_de.json`) for German output.
- ISO standards are referred to by name only.
- `knowledge_hash` is the SHA-256 over all files in `knowledge/data/`, recorded with every saved result.
