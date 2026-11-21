# Environmental claims RAG package: batches C01-C09, S01-S29, E01-E08, F01-F10 and R01-R04

This package turns EU and German green-claims law into data for your prototype. It is a research aid and does not replace legal review.

## Files

| File | Purpose |
|---|---|
| `data/chunks.jsonl` | 1166 source passages with citation, audience, validity, product group and warnings. Load these into the vector store. |
| `data/rules.jsonl` | 94 rules: 27 general, 37 product-specific, 14 on labels, evidence and carbon removals, 9 on company-level claims, and 7 that watch possible future law. Each has triggers, check questions, fixes, examples and verified legal quotes. |
| `data/eclass_routing.csv` | Which product rules each ECLASS segment adds. |
| `data/claim_object_routing.csv` | Rules added by claim topic, whatever the segment, such as packaging, EMAS or carbon removal claims. |
| `data/future_concordance_dfa.csv` | Shows where today's green-claim rules would move under the Digital Fairness Act proposal. |
| `data/standards_reference.csv` | ISO standards as metadata only, with the edition checked on 18 November 2026. |
| `data/concordance_eu_de.csv` | Links EU provisions to their German counterparts. |
| `data/source_manifest.csv` | Every uploaded file, how it was used, known issues and its SHA-256 hash. |

## Recommended pipeline

1. **Split** the uploaded text into single claims.
2. **Add context** to each claim: audience, channel, ECLASS segment, claim date, and whether the goods were on the market before 27 September 2026.
3. **Run the gates** `G01` to `G04`. Stop if the statement is not an environmental claim.
4. **Select candidate rules:**
   - all general rules (`scope.routing = "all"`)
   - the product rules listed for the ECLASS segment in `eclass_routing.csv`
   - the rules for the claim topic in `claim_object_routing.csv`
5. **Narrow the candidates.** Use `triggers` as a broad pre-filter, then let the model choose from the rule titles and requirements. A trigger alone is not a finding.
6. **Retrieve evidence in two ways:**
   - Load the chunks named in each candidate rule's `basis`, using `parent_id`.
   - Add a vector search with the filters below.
7. **Assess** each claim using only the retrieved passages.
8. **Rewrite** with the rule's `fix.templates`. Keep placeholders such as `[X]` until the company supplies verified facts.
9. **Check the output in code.** Reject any answer citing a chunk that was not retrieved.
10. **Add future notes** from the `FW` rules and `future_concordance_dfa.csv`. Keep them apart from the legal finding.
11. **Show the result to a human reviewer.**

If the ECLASS segment is missing or is 90, run the general rules and send the claim to manual review.

## Retrieval filters

```python
where = {
    "collection": {"$in": ["current_law", "interpretation"]},
    "currency": {"$ne": "superseded"},
    "audience": {"$contains": claim_audience},          # B2C or B2B
    "product_domains": {"$in": ["ALL"] + claim_domains},
}
```

- Exclude `collection = reference_only`.
- Show the `caution` field to the model with the passage.
- If sources conflict, prefer the lower `authority_rank`: 1 law, 2 case law and amending acts, 3 Commission guidance, 4 legislative reasoning, 5 translation.
- Use a multilingual embedding model, because German law stays in German while claims and output are in English.
- Embed `embed_text`. Show `text` and `locator` to the user.

## Dates that are not yet in force

Two adopted acts do not apply yet: Regulation (EU) 2026/405 from 23 September 2029 and Regulation (EU) 2026/1030 from 2 December 2030. Several PPWR and battery duties are also staged.

```python
is_future = (rule["scope"]["applies_from"] or "0000") > claim_date
```

If `is_future` is true, the rule can never produce a violation. Report it in `future_requirements`. Passages with `currency = adopted_not_yet_applicable` follow the same logic.

## Result types

| Status | Meaning |
|---|---|
| `NOT_A_CLAIM` | Gate `G01` was not met. |
| `PROHIBITED_LIKELY` | The conditions of a `prohibited` rule are visible in the text. |
| `HIGH_RISK` | A `case_by_case` rule applies and the claim may mislead. |
| `NEEDS_EVIDENCE` | The result depends on facts the system does not have. |
| `NO_ISSUE_FOUND` | No issue was found in the supplied text. Never output "compliant". |

Rules with severity `info` add advice and do not change the status.

## System prompt for the local model

```text
You assess one environmental claim using only the SOURCES provided.
Do not use outside knowledge. If the sources do not answer the question, return NEEDS_EVIDENCE.
Apply the RULE tests in order. Consider the audience: black-list rules apply only to consumers.
Apply a product rule only if the product falls within the rule's scope.
Never state that a fact is true unless it appears in the claim or the supplied company facts.
Keep placeholders such as [X] in rewritten claims. Never invent figures, certificates or dates.
Every finding must cite chunk_id values from SOURCES.
Follow the caution attached to a source. A proposal or future-law source can never support a violation.
Return JSON only:
{"claim":"","status":"","rule_ids":[],"reason":"","citations":[{"chunk_id":"","quote":""}],
 "facts_needed":[],"future_requirements":[],"improved_claim":"","human_review_required":true}
```

## Product rule groups

| Prefix | Product group | Prefix | Product group |
|---|---|---|---|
| `PK` | Packaging | `DT` | Detergents |
| `EN` | Energy-related and ecodesign products | `CS` | Cosmetics |
| `TY` | Tyres | `TX` | Textiles |
| `CA` | Passenger cars | `CN` | Construction products |
| `BA` | Batteries | `FD` | Food |
| `EE` | Electrical and electronic equipment | `OR` | Organic products |
| `CH` | Chemicals and articles | `WD` | Deforestation-free claims |
| `BI` | Biocides | `RE` | Renewable energy |
| `PP` | Plant protection products | `TR` | Transport emissions |
| `DU` | Durability guarantees and repair | `LB` | EU Ecolabel |
| `EM` | EMAS | `FP` | Footprint methods and proof |
| `CR` | Carbon removals | `RP` | Company reporting, Taxonomy and climate targets |

## Future law

Passages with `collection = future_law` are proposals or negotiating positions, not law. The standard retrieval filter above excludes them, so they cannot influence a finding.

Search this collection separately and only for the `FW` rules:

```python
future_where = {"collection": "future_law", "audience": {"$contains": claim_audience}}
```

- Rules `FW01` to `FW07` have severity `future`. They never change the status of a claim.
- A rule with the trigger `*` applies to every explicit environmental claim.
- Report each result in `future_requirements` and begin it with "Possible future requirement (not law):".
- Show the three Green Claims Directive versions separately using each rule's `positions` field. Never merge them into one requirement.

## Non-binding method guidance

Rules `FP01` to `FP05` rest on Commission Recommendation (EU) 2021/2279. They tell the system what proof to ask for and can only return `NEEDS_EVIDENCE`. They can never support a finding of a legal violation.

## ISO standards

ISO standards are listed as metadata only. The model may name a standard as a possible evidence route, but must not quote or summarise its content until a licence is confirmed.

## Known gaps

1. **Most older EU acts in batches S, E and R are original texts, not consolidated versions.** Their passages carry `currency = original_text_not_consolidated` and a warning. The most important replacements are RoHS, CLP, the Renewable Energy Directive, EUDR, the Batteries Regulation and the Consumer Rights Directive.
2. **EnVKV (S06) and TextilKennzG (S18) are missing.**
3. **C01 must be replaced.** The uploaded UCPD is the 2005 text.
4. **The CPC Common Understanding on old stock (30 June 2026) is missing.**
5. **The Taxonomy Disclosures Delegated Act is the 2021 version.** Delegated Regulation (EU) 2026/73 changed it from 1 January 2026.
6. **German CSRD transposition is open.** No transposition act was found on 18 November 2026, so rule `RP05` must be rechecked.
7. **ESRS duties bind reporting companies only.** For other companies, rules `RP06` to `RP09` are benchmarks.
8. **Digital Fairness Act Annexes I and II are missing.** The black list and correlation table are needed to confirm where each banned practice would move.
9. **Commission work programme Annex III is missing.** It is the source for the planned withdrawal of the Green Claims Directive.
10. **The Consumer Package proposals (F06) are missing.** The uploaded file is a general web page.
11. **Many PPWR methods do not exist yet.** Rule `PK01` needs human review where no calculation method has been adopted.
12. **ECLASS routing works at segment level.** Validate it with the company's product data.
13. **The Blue Angel criteria (E08) are missing.** They are needed only for the company's product groups.
14. **The EU Ecolabel and EMAS texts are original versions.** Replace them with the consolidated versions.
15. **CRCF methodologies are not included.** They are set in separate delegated acts.

## Validation results

- All 323 legal quotes in the rules were found word for word in their source passages.
- About 99 % of the batch S passage text matched the source PDFs in a 40-character comparison. The differences come from page breaks, removed footnote markers and repaired subscripts such as CO2.
- All 38 product-rule examples and all 14 label and evidence examples triggered their own rule. Every rule can be reached through the routing tables.
- A keyword retrieval test found a supporting passage in the top 8 for 33 of 38 product-rule examples, 14 of 14 label and evidence examples, and 7 of 9 company-level examples. It used the rule title as well as the claim, so it is a sanity check rather than a measure of real performance. Passages named in a rule's `basis` are loaded directly in the pipeline.
- Code checks confirm that no general, product, label or evidence rule cites a future-law passage, and that every future rule cites all three Green Claims Directive versions.
- The rules have not yet been reviewed by a lawyer or tested with Ollama.
