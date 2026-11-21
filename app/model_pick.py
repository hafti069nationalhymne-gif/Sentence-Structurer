"""Choose the Ollama Cloud model for this app from the models the API key can use.

The model only rewrites one short sentence, translates it into German and writes a two-sentence
explanation as strict JSON. What matters: instruction following, good German, reliable JSON output,
speed. Ranking (best first) — Qwen is preferred, as requested by the user of this prototype:

    1. Qwen (not coder / vision)    instruction following, strong German, reliable JSON; small and fast
    2. Mistral                      very good German (European model), reliable JSON
    3. Gemma                        multilingual, mid-size
    4. gpt-oss:20b                  small general model with dependable structured output
    5. "flash" variants             fast general models
    6. other large general models   work, but slower than needed for one sentence
    Excluded: code, vision, OCR and embedding models. Unknown names come last.
Within a group, smaller models (by the parameter count in the tag) come first.
"""
from __future__ import annotations

import re

from .ollama_client import OllamaClient, OllamaError

GROUPS: list[tuple[str, str]] = [
    (r"^qwen", "Qwen: strong instruction following and German, reliable JSON"),
    (r"^(mistral|ministral|magistral)", "Mistral: very good German, reliable JSON"),
    (r"^gemma", "Gemma: multilingual, mid-size"),
    (r"^gpt-oss:20b", "gpt-oss:20b: small general model with dependable JSON"),
    (r"flash", "fast general model"),
    (r"^(gpt-oss|glm|deepseek|minimax|mimo|nemotron|kimi|llama)", "large general model"),
]
EXCLUDE = re.compile(r"code|coder|-vl\b|vision|ocr|embed", re.I)

JSON_SCHEMA = {"type": "object", "properties": {"sentence": {"type": "string"}, "count": {"type": "integer"}},
               "required": ["sentence", "count"]}


def _size(name: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)b\b", name.lower())
    return float(m.group(1)) if m else 1000.0


def rank_models(models: list[str]) -> list[tuple[str, str]]:
    """[(model, reason)] best first, excluding unsuitable models."""
    ranked = []
    for m in dict.fromkeys(models):
        if not m or EXCLUDE.search(m):
            continue
        base = m.removesuffix("-cloud")
        group = next((i for i, (rx, _) in enumerate(GROUPS) if re.search(rx, base, re.I)), len(GROUPS))
        reason = GROUPS[group][1] if group < len(GROUPS) else "unknown model, tried last"
        ranked.append((group, _size(base), base, m, reason))
    ranked.sort()
    return [(m, reason) for _, _, _, m, reason in ranked]


def json_test(client: OllamaClient, model: str) -> tuple[bool, str]:
    try:
        out = client.chat_json(model, "Answer with JSON only.",
                               'Return {"sentence": "The cap is not included.", "count": 3} exactly.', JSON_SCHEMA)
    except OllamaError as e:
        return False, str(e).replace("Chat call failed: ", "")
    ok = isinstance(out.get("sentence"), str) and isinstance(out.get("count"), int)
    return ok, "passed the JSON test" if ok else f"returned unusable JSON: {out}"


def pick_model(client: OllamaClient, max_probes: int = 5) -> dict:
    """List the key's models, rank them and probe the best ones in order. Never raises.

    Returns {"model", "reason", "ok", "tried": [(model, ok, note)], "available": [...]}.
    ok=False means no model answered; "model" is then the best-ranked one (used once the account works).
    """
    try:
        available = client.tags()
    except OllamaError as e:
        return {"model": None, "reason": str(e), "ok": False, "tried": [], "available": []}
    ranked = rank_models(available)
    if not ranked:
        return {"model": None, "reason": "the key offers no suitable model", "ok": False, "tried": [], "available": available}
    tried = []
    for model, why in ranked[:max_probes]:
        ok, note = json_test(client, model)
        tried.append((model, ok, note))
        if ok:
            return {"model": model, "reason": why, "ok": True, "tried": tried, "available": available}
        if any(w in note for w in ("usage credits", "API key was rejected", "usage limit")):
            break  # an account problem: other models will fail the same way
    best, why = ranked[0]
    return {"model": best, "reason": f"{why} (not yet usable: {tried[-1][2]})", "ok": False, "tried": tried,
            "available": available}
