"""Loader for the read-only knowledge package in knowledge/data.

Every record is validated with pydantic. Field names follow the files exactly.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from .config import KNOWLEDGE_DIR

Severity = Literal["gate", "prohibited", "case_by_case", "evidence", "info", "future"]
Routing = Literal["all", "eclass", "claim_object", "future_watch"]

EXPECTED_CHUNKS = 1166
EXPECTED_RULES = 94

LEGAL_STATUS = {
    "binding_law": "Binding law",
    "amending_act": "Binding law (amending act)",
    "case_law": "Case law",
    "soft_law": "Commission guidance (non-binding)",
    "legislative_reasoning": "Legislative reasoning (non-binding)",
    "translation": "Unofficial translation",
    "legislative_proposal": "Proposal (not law)",
    "negotiating_position": "Negotiating position (not law)",
}
FUTURE_ROLES = {"proposal", "parliament_position", "council_position"}


class Chunk(BaseModel):
    model_config = ConfigDict(extra="allow")
    chunk_id: str
    parent_id: str
    part: str
    doc_id: str
    doc_title: str
    locator: str
    jurisdiction: Literal["EU", "DE"]
    language: Literal["en", "de"]
    source_type: Literal[tuple(LEGAL_STATUS)]  # type: ignore[valid-type]
    authority_rank: int
    collection: Literal["current_law", "interpretation", "future_law", "reference_only"]
    audience: list[Literal["B2C", "B2B"]]
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    currency: str
    caution: Optional[str] = None
    product_domains: list[str]
    text: str

    @property
    def part_no(self) -> int:
        return int(self.part.split("/")[0])


class Basis(BaseModel):
    chunk: str
    role: str
    quote: str


class Example(BaseModel):
    claim: str
    finding: Optional[str] = None
    better: Optional[str] = None
    source: Optional[str] = None


class Fix(BaseModel):
    strategy: str
    templates: list[str]
    avoid: list[str]


class Scope(BaseModel):
    list_ids: list[str]
    product_domains: list[str]
    channels: list[str]
    routing: Routing
    applies_from: Optional[str] = None
    claim_object: Optional[str] = None

    @field_validator("applies_from")
    @classmethod
    def _iso(cls, v):
        if v is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError(f"applies_from must be ISO date, got {v!r}")
        return v


class Position(BaseModel):
    version: str
    summary: str


class Rule(BaseModel):
    model_config = ConfigDict(extra="allow")
    rule_id: str
    title: str
    group: str
    severity: Severity
    audience: list[Literal["B2C", "B2B"]]
    claim_types: list[str]
    requirement: str
    triggers: list[str]
    test: list[str]
    facts_needed: list[str]
    passes_if: list[str]
    exceptions: list[str]
    fix: Fix
    examples: list[Example]
    basis: list[Basis]
    notes: Optional[str] = None
    positions: list[Position]
    scope: Scope


@dataclass
class VerifiedQuote:
    rule_id: str
    parent_id: str
    role: str
    quote: str
    chunk: Chunk  # the part that contains the quote


@dataclass
class Knowledge:
    chunks: dict[str, Chunk]
    parents: dict[str, list[Chunk]]
    rules: dict[str, Rule]
    eclass: list[dict]
    claim_object_routing: list[dict]
    concordance_eu_de: list[dict]
    future_concordance_dfa: list[dict]
    standards: list[dict]
    manifest: list[dict]
    knowledge_hash: str
    quotes: dict[str, list[VerifiedQuote]] = field(default_factory=dict)
    quote_failures: list[str] = field(default_factory=list)
    _bm25: "BM25 | None" = None

    # ---- lookups -------------------------------------------------------
    def parent_parts(self, parent_id: str) -> list[Chunk]:
        return self.parents.get(parent_id, [])

    def segment(self, seg: str) -> dict | None:
        for row in self.eclass:
            if row["eclass_segment"] == str(seg):
                return row
        return None

    def segment_rule_ids(self, seg: str) -> list[str]:
        row = self.segment(seg)
        return split_ids(row["product_rule_ids"]) if row else []

    def claim_object_rule_ids(self, claim_object: str) -> list[str]:
        for row in self.claim_object_routing:
            if row["claim_object"] == claim_object:
                return split_ids(row["rule_ids"])
        return []

    def german_counterparts(self, chunk_or_parent: str, rule_id: str | None = None) -> list[dict]:
        out = []
        for row in self.concordance_eu_de:
            if row["eu_chunk_id"] == chunk_or_parent:
                out.append(row)
        if not out and rule_id:
            out = [r for r in self.concordance_eu_de if r["rule_id"] == rule_id]
        return out

    def dfa_rows(self, rule_id: str) -> list[dict]:
        return [r for r in self.future_concordance_dfa if rule_id in split_ids(r["rule_ids"])]

    def search(self, query: str, k: int = 8, include_future: bool = False) -> list[tuple[Chunk, float]]:
        if self._bm25 is None:
            self._bm25 = BM25([c for c in self.chunks.values() if c.collection != "reference_only"])
        res = self._bm25.search(query, k=k * 3)
        if not include_future:
            res = [(c, s) for c, s in res if c.collection != "future_law"]
        return res[:k]


def split_ids(s: str | None) -> list[str]:
    return [p.strip() for p in (s or "").split(";") if p.strip()]


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def hash_dir(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if p.is_file():
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def load_knowledge(path: Path = KNOWLEDGE_DIR, strict_counts: bool = True) -> Knowledge:
    if not (path / "chunks.jsonl").exists():
        raise FileNotFoundError(
            f"Knowledge base not found in {path}. Unzip Environmental_Claims_RAG_Complete.zip into knowledge/."
        )
    chunks: dict[str, Chunk] = {}
    with (path / "chunks.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = Chunk.model_validate_json(line)
                if c.chunk_id in chunks:
                    raise ValueError(f"duplicate chunk_id {c.chunk_id}")
                chunks[c.chunk_id] = c
    rules: dict[str, Rule] = {}
    with (path / "rules.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = Rule.model_validate_json(line)
                if r.rule_id in rules:
                    raise ValueError(f"duplicate rule_id {r.rule_id}")
                rules[r.rule_id] = r
    if strict_counts and (len(chunks) != EXPECTED_CHUNKS or len(rules) != EXPECTED_RULES):
        raise ValueError(f"expected {EXPECTED_CHUNKS} chunks / {EXPECTED_RULES} rules, got {len(chunks)} / {len(rules)}")

    parents: dict[str, list[Chunk]] = defaultdict(list)
    for c in chunks.values():
        parents[c.parent_id].append(c)
    for p in parents.values():
        p.sort(key=lambda c: c.part_no)

    kb = Knowledge(
        chunks=chunks,
        parents=dict(parents),
        rules=rules,
        eclass=_read_csv(path / "eclass_routing.csv"),
        claim_object_routing=_read_csv(path / "claim_object_routing.csv"),
        concordance_eu_de=_read_csv(path / "concordance_eu_de.csv"),
        future_concordance_dfa=_read_csv(path / "future_concordance_dfa.csv"),
        standards=_read_csv(path / "standards_reference.csv"),
        manifest=_read_csv(path / "source_manifest.csv"),
        knowledge_hash=hash_dir(path),
    )
    _verify_quotes(kb)
    _verify_routing(kb)
    return kb


def _verify_quotes(kb: Knowledge) -> None:
    for r in kb.rules.values():
        vq: list[VerifiedQuote] = []
        for b in r.basis:
            parts = kb.parent_parts(b.chunk)
            if not parts:
                kb.quote_failures.append(f"{r.rule_id}: basis parent {b.chunk} not found")
                continue
            hit = next((p for p in parts if b.quote in p.text), None)
            if hit is None:
                kb.quote_failures.append(f"{r.rule_id}: quote not found in {b.chunk}: {b.quote[:60]}")
                continue
            vq.append(VerifiedQuote(r.rule_id, b.chunk, b.role, b.quote, hit))
        kb.quotes[r.rule_id] = vq


def _verify_routing(kb: Knowledge) -> None:
    for row in kb.eclass:
        for rid in split_ids(row["product_rule_ids"]):
            if rid not in kb.rules:
                raise ValueError(f"eclass segment {row['eclass_segment']} routes unknown rule {rid}")
    for row in kb.claim_object_routing:
        for rid in split_ids(row["rule_ids"]):
            if rid not in kb.rules:
                raise ValueError(f"claim object {row['claim_object']} routes unknown rule {rid}")


@lru_cache(maxsize=1)
def get_knowledge() -> Knowledge:
    return load_knowledge()


# ---- small BM25 for the "more sources" view --------------------------------
_TOKEN = re.compile(r"[a-zäöüß0-9]+", re.I)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text) if len(t) > 1]


class BM25:
    def __init__(self, docs: list[Chunk], k1: float = 1.4, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.tf = [Counter(tokenize(f"{d.doc_title} {d.locator} {d.text}")) for d in docs]
        self.len = [sum(t.values()) for t in self.tf]
        self.avg = sum(self.len) / max(1, len(self.len))
        df: Counter = Counter()
        for t in self.tf:
            df.update(t.keys())
        n = len(docs)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}

    def search(self, query: str, k: int = 8) -> list[tuple[Chunk, float]]:
        q = tokenize(query)
        scores = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for w in q:
                if w in tf:
                    f = tf[w]
                    s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            if s > 0:
                scores.append((s, i))
        scores.sort(reverse=True)
        return [(self.docs[i], round(s, 3)) for s, i in scores[:k]]
