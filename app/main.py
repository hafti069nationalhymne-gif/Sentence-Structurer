"""ClaimComposer local server. Run with:  uv run python -m app.main [--open] [--port N]

The server binds to 127.0.0.1 only. There is no account, cloud service or telemetry.
"""
from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import BIND_HOST, LOG_DIR, STATIC_DIR, USERDATA_DIR, key_file_status, load_api_key, load_settings, save_api_key, save_settings
from .engine.context import AnswerError, segment_options
from .engine.evidence import sources_for_rule
from .engine.recommend import adjust_one, recommend, revalidate, route_summary
from .knowledge import get_knowledge
from .library import get_library
from .ollama_client import OllamaClient, make_client
from .schemas import (
    ClearRequest, EventRequest, RecommendRequest, RevalidateRequest, ReviewRequest, SettingsUpdate, SusRequest,
    UsabilityRequest,
)
from .storage import Store

log = logging.getLogger("claimcomposer")


def create_app(userdata: Path | None = None, ollama_transport=None) -> FastAPI:
    userdata = Path(userdata or USERDATA_DIR)
    kb = get_knowledge()
    lib = get_library()
    state = {"settings": load_settings(userdata=userdata)}
    store = Store(userdata / "claimcomposer.sqlite")

    def client() -> OllamaClient:
        c = make_client(state["settings"], userdata, transport=ollama_transport)
        s = state["settings"]
        if s.cloud and s.cloud_model == "auto" and not s.cloud_model_resolved:
            # Pick the best-fitting model the key offers (ranking only; the launcher also tests it).
            from .model_pick import rank_models
            try:
                ranked = rank_models(c.tags())
                if ranked:
                    s.cloud_model_resolved = ranked[0][0]
            except Exception:  # noqa: BLE001 - status() reports the problem
                pass
        return c

    app = FastAPI(title="ClaimComposer", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Defence in depth: refuse requests that do not come from this machine.
        host = request.client.host if request.client else "127.0.0.1"
        if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
            return JSONResponse({"detail": "local access only"}, status_code=403)
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'")  # the browser never talks to ollama.com; the server does
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    @app.exception_handler(AnswerError)
    async def answer_error(_, exc: AnswerError):
        return JSONResponse({"detail": "invalid answers", "errors": exc.errors}, status_code=422)

    # ---- data for the questionnaire -------------------------------------------------
    @app.get("/api/questionnaire")
    def questionnaire():
        return {"questionnaire": lib.questionnaire, "segments": segment_options(kb, lib),
                "library_hash": lib.library_hash, "knowledge_hash": kb.knowledge_hash}

    @app.post("/api/route")
    def route(body: RecommendRequest):
        return route_summary(body.answers.model_dump(exclude_none=True), kb, lib)

    @app.post("/api/recommend")
    def do_recommend(body: RecommendRequest):
        answers = body.answers.model_dump(exclude_none=True)
        s = state["settings"]
        res = recommend(answers, kb, lib, s, client() if (body.use_ai and s.ollama_enabled) else None, use_ai=body.use_ai)
        if body.save:
            res["ticket_id"] = store.save_ticket(answers, res, body.session_id)
        return res

    @app.post("/api/revalidate")
    def do_revalidate(body: RevalidateRequest):
        return revalidate(body.answers.model_dump(exclude_none=True), body.template_id, body.values, kb, lib)

    @app.post("/api/adjust")
    def do_adjust(body: RevalidateRequest):
        s = state["settings"]
        return adjust_one(body.answers.model_dump(exclude_none=True), body.template_id, body.values, kb, lib, s,
                          client() if s.ollama_enabled else None)

    @app.get("/api/sources/{rule_id}")
    def sources(rule_id: str):
        if rule_id not in kb.rules:
            raise HTTPException(404, "unknown rule")
        r = kb.rules[rule_id]
        return {"rule_id": rule_id, "title": r.title, "requirement": r.requirement, "severity": r.severity,
                "notes": r.notes, "passages": sources_for_rule(rule_id, kb)}

    @app.get("/api/search")
    def search(q: str, k: int = 8):
        q = q[:200]
        return {"query": q, "results": [
            {"chunk_id": c.chunk_id, "doc_title": c.doc_title, "locator": c.locator, "jurisdiction": c.jurisdiction,
             "legal_status": c.source_type, "collection": c.collection, "caution": c.caution, "score": s,
             "text": c.text[:900]} for c, s in kb.search(q, k=min(max(k, 1), 20))]}

    # ---- status and settings ---------------------------------------------------------
    @app.get("/api/status")
    def status():
        s = state["settings"]
        st = client().status(s.active_model) if s.ollama_enabled else None
        mode = "ai" if (st and st.available and st.model_present) else "template"
        if not s.ollama_enabled:
            msg = "AI is switched off. Template mode."
        else:
            msg = st.message
        return {"mode": mode, "message": msg, "ollama": st.as_dict() if st else None, "settings": s.public(),
                "ai_source": s.ai_source, "api_key_set": bool(load_api_key(userdata)),
                "api_key_from_file": key_file_status()[0] == "ok",
                "library_hash": lib.library_hash, "knowledge_hash": kb.knowledge_hash,
                "templates": len(lib.templates), "bind_host": BIND_HOST}

    @app.post("/api/settings")
    def update_settings(body: SettingsUpdate):
        s = state["settings"]
        patch = body.model_dump(exclude_none=True)
        key = patch.pop("api_key", None)
        if key is not None:
            try:
                save_api_key(key, userdata)  # write-only: the key is never returned
            except ValueError as e:
                raise HTTPException(422, str(e))
        for k, v in patch.items():
            setattr(s, k, v)
        save_settings(s, userdata)
        return {**s.public(), "api_key_set": bool(load_api_key(userdata))}

    # ---- history, review, usability ---------------------------------------------------
    @app.get("/api/history")
    def history():
        return {"tickets": store.history()}

    @app.get("/api/history/{ticket_id}")
    def ticket(ticket_id: int):
        t = store.ticket(ticket_id)
        if not t:
            raise HTTPException(404, "unknown ticket")
        return t

    @app.get("/api/export")
    def export(format: str = "json", ticket_id: int | None = None):
        try:
            content, media, name = store.export(format, ticket_id)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return Response(content, media_type=media + "; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/review")
    def review(body: ReviewRequest):
        rid = store.save_review(body.ticket_id, body.template_id, body.fits, body.would_use, body.comment)
        return {"ok": True, "id": rid}

    @app.post("/api/usability")
    def usability(body: UsabilityRequest):
        return {"ok": True, "id": store.save_usability(body.session_id, body.ticket_id, body.question_times,
                                                        body.back_steps, body.time_to_first_copy_ms)}

    @app.post("/api/sus")
    def sus(body: SusRequest):
        try:
            return {"ok": True, "score": store.save_sus(body.session_id, body.answers)}
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.get("/api/export/usability.csv")
    def usability_csv():
        return PlainTextResponse(store.export_usability_csv(), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": 'attachment; filename="claimcomposer-usability.csv"'})

    @app.post("/api/events")
    def events(body: EventRequest):
        store.save_event(body.session_id, body.ticket_id, body.type, body.payload)
        return {"ok": True}

    @app.post("/api/clear")
    def clear(body: ClearRequest):
        store.clear()
        return {"ok": True}

    # ---- static frontend ----------------------------------------------------------
    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.state.store = store
    app.state.settings = state
    return app


def free_port(preferred: int = 0) -> int:
    if preferred:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((BIND_HOST, preferred))
                return preferred
            except OSError:
                pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((BIND_HOST, 0))
        return s.getsockname()[1]


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    p = argparse.ArgumentParser(description="ClaimComposer local server")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--open", action="store_true", help="open the app window when the server is ready")
    args = p.parse_args(argv)
    LOG_DIR.mkdir(exist_ok=True)
    USERDATA_DIR.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, filename=LOG_DIR / "server.log",
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    port = free_port(args.port if args.port is not None else settings.port)
    url = f"http://{BIND_HOST}:{port}/"
    (USERDATA_DIR / "server_url.txt").write_text(url, encoding="utf-8")
    print(f"ClaimComposer is running at {url}  (close this window to stop it)", flush=True)
    if args.open:
        threading.Timer(1.2, lambda: open_app_window(url)).start()
    uvicorn.run(create_app(), host=BIND_HOST, port=port, log_level="warning")
    return 0


def open_app_window(url: str) -> None:
    """Open the app in its own window (Edge or Chrome --app=), or else the default browser."""
    import shutil
    import subprocess

    candidates = []
    if sys.platform.startswith("win"):
        import os
        pf = [os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")]
        candidates = [Path(b) / "Microsoft/Edge/Application/msedge.exe" for b in pf] + \
                     [Path(b) / "Google/Chrome/Application/chrome.exe" for b in pf]
    elif sys.platform == "darwin":
        candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                      Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]
    else:
        for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            w = shutil.which(name)
            if w:
                candidates.append(Path(w))
    for exe in candidates:
        if exe and exe.exists():
            try:
                subprocess.Popen([str(exe), f"--app={url}", "--window-size=1440,960"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                continue
    webbrowser.open(url)


if __name__ == "__main__":
    sys.exit(main())
