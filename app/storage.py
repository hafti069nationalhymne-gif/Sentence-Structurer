"""Local SQLite store for tickets, results, reviewer feedback and usability data.

Nothing leaves the machine. Comments are the only free text and are never sent to the model.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  session_id TEXT,
  answers_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  library_hash TEXT, knowledge_hash TEXT, mode TEXT, model TEXT, duration_ms INTEGER
);
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  ticket_id INTEGER, template_id TEXT, fits TEXT, would_use INTEGER, comment TEXT
);
CREATE TABLE IF NOT EXISTS usability (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  session_id TEXT, ticket_id INTEGER, question_times_json TEXT, back_steps INTEGER, time_to_first_copy_ms INTEGER
);
CREATE TABLE IF NOT EXISTS sus (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  session_id TEXT, answers_json TEXT, score REAL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  session_id TEXT, ticket_id INTEGER, type TEXT, payload_json TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sus_score(answers: list[int]) -> float:
    """System Usability Scale: 10 items, 1-5. Odd items positive, even items negative. Result 0-100."""
    if len(answers) != 10 or not all(isinstance(a, int) and 1 <= a <= 5 for a in answers):
        raise ValueError("SUS needs 10 answers from 1 to 5")
    total = sum((a - 1) if i % 2 == 0 else (5 - a) for i, a in enumerate(answers))
    return total * 2.5


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    # ---- writes ---------------------------------------------------------------
    def save_ticket(self, answers: dict, result: dict, session_id: str | None = None) -> int:
        run = result.get("run", {})
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO tickets (created_at, session_id, answers_json, result_json, library_hash, knowledge_hash, mode, model, duration_ms)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (now(), session_id, json.dumps(answers, ensure_ascii=False), json.dumps(result, ensure_ascii=False),
                 run.get("library_hash"), run.get("knowledge_hash"), run.get("mode"), run.get("chat_model"), run.get("duration_ms")))
            return int(cur.lastrowid)

    def save_review(self, ticket_id: int | None, template_id: str, fits: str | None, would_use: int | None, comment: str | None) -> int:
        if fits not in (None, "yes", "no", "unsure"):
            raise ValueError("fits must be yes, no or unsure")
        if would_use is not None and not (1 <= int(would_use) <= 5):
            raise ValueError("would_use must be 1 to 5")
        comment = (comment or "")[:2000]
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO reviews (created_at, ticket_id, template_id, fits, would_use, comment) VALUES (?,?,?,?,?,?)",
                            (now(), ticket_id, template_id, fits, would_use, comment))
            return int(cur.lastrowid)

    def save_usability(self, session_id: str, ticket_id: int | None, question_times: dict, back_steps: int,
                       time_to_first_copy_ms: int | None) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO usability (created_at, session_id, ticket_id, question_times_json, back_steps, time_to_first_copy_ms)"
                            " VALUES (?,?,?,?,?,?)",
                            (now(), session_id, ticket_id, json.dumps(question_times), int(back_steps), time_to_first_copy_ms))
            return int(cur.lastrowid)

    def save_sus(self, session_id: str, answers: list[int]) -> float:
        score = sus_score(answers)
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO sus (created_at, session_id, answers_json, score) VALUES (?,?,?,?)",
                      (now(), session_id, json.dumps(answers), score))
        return score

    def save_event(self, session_id: str | None, ticket_id: int | None, type_: str, payload: dict | None = None) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO events (created_at, session_id, ticket_id, type, payload_json) VALUES (?,?,?,?,?)",
                      (now(), session_id, ticket_id, type_, json.dumps(payload or {})))

    def clear(self) -> None:
        with self._lock, self._conn() as c:
            for t in ("tickets", "reviews", "usability", "sus", "events"):
                c.execute(f"DELETE FROM {t}")
            c.execute("DELETE FROM sqlite_sequence")

    # ---- reads ---------------------------------------------------------------
    def history(self, limit: int = 100) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT id, created_at, answers_json, mode, model, library_hash, knowledge_hash, result_json "
                             "FROM tickets ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            res = json.loads(r["result_json"])
            out.append({"id": r["id"], "created_at": r["created_at"], "answers": json.loads(r["answers_json"]),
                        "mode": r["mode"], "model": r["model"], "library_hash": r["library_hash"],
                        "knowledge_hash": r["knowledge_hash"], "n_recommendations": len(res.get("recommendations", [])),
                        "topic_label": res.get("context", {}).get("topic_label")})
        return out

    def ticket(self, ticket_id: int) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "created_at": r["created_at"], "answers": json.loads(r["answers_json"]),
                "result": json.loads(r["result_json"]), "mode": r["mode"], "model": r["model"],
                "library_hash": r["library_hash"], "knowledge_hash": r["knowledge_hash"]}

    def table(self, name: str) -> list[dict]:
        assert name in ("tickets", "reviews", "usability", "sus", "events")
        with self._conn() as c:
            return [dict(r) for r in c.execute(f"SELECT * FROM {name} ORDER BY id").fetchall()]

    # ---- exports ---------------------------------------------------------------
    def export(self, fmt: str, ticket_id: int | None = None) -> tuple[str, str, str]:
        """Return (content, media type, filename)."""
        tickets = [self.ticket(ticket_id)] if ticket_id else [self.ticket(h["id"]) for h in reversed(self.history(100000))]
        tickets = [t for t in tickets if t]
        reviews = self.table("reviews")
        stem = f"claimcomposer-ticket-{ticket_id}" if ticket_id else "claimcomposer-log"
        if fmt == "json":
            data = {"tickets": tickets, "reviews": [r for r in reviews if not ticket_id or r["ticket_id"] == ticket_id]}
            return json.dumps(data, ensure_ascii=False, indent=2), "application/json", stem + ".json"
        if fmt == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["ticket_id", "created_at", "mode", "model", "library_hash", "knowledge_hash", "segment", "audience",
                        "channel", "topic", "scope", "evidence", "language", "rank", "template_id", "specificity",
                        "ai_adjusted", "sentence", "rule_ids", "review_fits", "review_would_use", "review_comment"])
            for t in tickets:
                a = t["answers"]
                for i, rec in enumerate(t["result"].get("recommendations", []), 1):
                    rv = [r for r in reviews if r["ticket_id"] == t["id"] and r["template_id"] == rec["template_id"]]
                    last = rv[-1] if rv else {}
                    w.writerow([t["id"], t["created_at"], t["mode"], t["model"], t["library_hash"], t["knowledge_hash"],
                                a.get("segment"), a.get("audience"), a.get("channel"), a.get("topic"), a.get("scope"),
                                a.get("evidence"), a.get("language"), i, rec["template_id"], rec["specificity"],
                                rec.get("ai_adjusted"), rec["sentence"], " ".join(rec.get("rule_ids", [])),
                                last.get("fits"), last.get("would_use"), last.get("comment")])
            return buf.getvalue(), "text/csv", stem + ".csv"
        if fmt == "md":
            lines = ["# ClaimComposer results", "", "Research prototype. Not legal advice. Human review required.", ""]
            for t in tickets:
                res, a = t["result"], t["answers"]
                lines += [f"## Ticket {t['id']} ({t['created_at']})", "",
                          f"- Product: {a.get('segment')} · Audience: {a.get('audience')} · Channel: {a.get('channel')} · "
                          f"Topic: {a.get('topic')} · Scope: {a.get('scope')} · Evidence: {a.get('evidence')}",
                          f"- Mode: {t['mode']} · Model: {t['model'] or '–'} · Library {t['library_hash']} · Knowledge {t['knowledge_hash']}", ""]
                for i, rec in enumerate(res.get("recommendations", []), 1):
                    lines += [f"### {i}. {rec['sentence']}", "", f"*{rec.get('status_line', '')}*", "",
                              f"Why it fits: {rec['why_it_fits']}", "", "Regulations:"]
                    for g in rec["regulations"]:
                        lines.append(f"- {g['rule_id']} · {g['doc_title']}, {g['locator']} ({g['legal_status']}): “{g['quote']}”")
                    lines += ["", "Facts to verify:"] + [f"- {f}" for f in rec["facts_to_verify"]] + [""]
                if res.get("dont_say"):
                    lines += ["### Don't say", ""] + [f"- ~~{d['phrase']}~~ ({d['rule_id']}): {d['reason']}" for d in res["dont_say"][:25]] + [""]
                if res.get("future_requirements"):
                    lines += ["### Future notes", ""] + [f"- {f['text']}" for f in res["future_requirements"]] + [""]
            return "\n".join(lines), "text/markdown", stem + ".md"
        raise ValueError("format must be json, csv or md")

    def export_usability_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["record", "id", "created_at", "session_id", "ticket_id", "question_times_ms", "back_steps",
                    "time_to_first_copy_ms", "sus_answers", "sus_score"])
        for r in self.table("usability"):
            w.writerow(["usability", r["id"], r["created_at"], r["session_id"], r["ticket_id"], r["question_times_json"],
                        r["back_steps"], r["time_to_first_copy_ms"], "", ""])
        for r in self.table("sus"):
            w.writerow(["sus", r["id"], r["created_at"], r["session_id"], "", "", "", "", r["answers_json"], r["score"]])
        return buf.getvalue()
