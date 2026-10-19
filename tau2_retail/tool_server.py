"""Serve the tau2-bench retail tools to Oumi endpoint tool implementations.

Oumi POSTs each tool call's arguments as JSON to the implementation's URL and
sends the conversation's id in the X-Oumi-Session-Id header. That id is the
dataset row id, so it repeats in every evaluation of the same dataset. Each
evaluation run therefore gets its own URL prefix, /runs/<run_id>/tools/<tool>,
and every (run, session) pair gets its own fresh copy of the retail store: one
conversation's changes never leak into another, in this run or any other, and
later calls in a conversation see its earlier changes. /tools/<tool> without a
run prefix is the "default" run, for manual testing.

A 2xx body is the tool's output. A tool refusing a call (for example cancelling
a delivered order) answers 400, which Oumi shows the model as the tool's error.

Run with the tau2 venv, from tau2_retail/ with ../.env loaded:
    TOOL_SERVER_CALL_LOG=logs/calls.jsonl ../.venv/bin/uvicorn tool_server:app --port 8765
"""

import json
import logging
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from tau2.domains.retail.environment import get_environment
from tau2.environment.environment import Environment

API_KEY_ENV_VAR = "TOOL_SERVER_API_KEY"
CALL_LOG_PATH_ENV_VAR = "TOOL_SERVER_CALL_LOG"
DEFAULT_RUN_ID = "default"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
SESSION_IDLE_SECONDS = 2 * 60 * 60
MAX_SESSIONS = 300
# Oumi shows the model the first 200 characters of an error body.
MAX_ERROR_LENGTH = 180

logger = logging.getLogger("tool_server")


@dataclass
class Session:
    environment: Environment
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_used: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class SessionKey:
    run_id: str
    session_id: str


class SessionStore:
    """One retail store per (run, session), evicted when idle or over capacity."""

    def __init__(self):
        self._sessions: OrderedDict[SessionKey, Session] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: SessionKey) -> Session:
        with self._lock:
            self._evict_idle()
            session = self._sessions.get(key)
            if session is None:
                session = Session(environment=get_environment())
                self._sessions[key] = session
                while len(self._sessions) > MAX_SESSIONS:
                    self._sessions.popitem(last=False)
            self._sessions.move_to_end(key)
            session.last_used = time.monotonic()
            return session

    def peek(self, key: SessionKey) -> Session | None:
        with self._lock:
            return self._sessions.get(key)

    def _evict_idle(self) -> None:
        cutoff = time.monotonic() - SESSION_IDLE_SECONDS
        for key in [k for k, s in self._sessions.items() if s.last_used < cutoff]:
            del self._sessions[key]


class CallLog:
    """Appends one JSON line per tool call, for debugging a conversation later."""

    def __init__(self, path: str | None):
        self._path = path
        self._lock = threading.Lock()

    def write(self, entry: dict) -> None:
        if not self._path:
            return
        with self._lock, open(self._path, "a") as log_file:
            log_file.write(json.dumps(entry) + "\n")


app = FastAPI(title="tau2 retail tools")
sessions = SessionStore()
call_log = CallLog(os.environ.get(CALL_LOG_PATH_ENV_VAR))
tool_names = {tool.name for tool in get_environment().get_tools()}


def _require_api_key(api_key: str | None) -> None:
    expected = os.environ.get(API_KEY_ENV_VAR)
    if not expected:
        raise HTTPException(status_code=500, detail="Server has no API key set")
    if api_key is None or not secrets.compare_digest(api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")


def _require_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.match(run_id):
        raise HTTPException(
            status_code=400, detail="Run id must be 1-64 letters, digits, '.', '_' or '-'"
        )


def _to_json(result: object) -> object:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if isinstance(result, list):
        return [_to_json(item) for item in result]
    return result


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "tools": len(tool_names)}


@app.post("/runs/{run_id}/tools/{tool_name}")
async def call_run_tool(
    run_id: str,
    tool_name: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_oumi_session_id: str | None = Header(default=None),
    x_oumi_call_id: str | None = Header(default=None),
) -> JSONResponse:
    _require_run_id(run_id)
    return await _handle_call(
        run_id, tool_name, request, x_api_key, x_oumi_session_id, x_oumi_call_id
    )


@app.post("/tools/{tool_name}")
async def call_default_tool(
    tool_name: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_oumi_session_id: str | None = Header(default=None),
    x_oumi_call_id: str | None = Header(default=None),
) -> JSONResponse:
    return await _handle_call(
        DEFAULT_RUN_ID, tool_name, request, x_api_key, x_oumi_session_id, x_oumi_call_id
    )


async def _handle_call(
    run_id: str,
    tool_name: str,
    request: Request,
    api_key: str | None,
    session_id: str | None,
    call_id: str | None,
) -> JSONResponse:
    _require_api_key(api_key)
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing X-Oumi-Session-Id header")
    if tool_name not in tool_names:
        return JSONResponse({"error": f"Unknown tool: {tool_name}"}, status_code=404)
    try:
        arguments = await request.json()
    except json.JSONDecodeError:
        arguments = None
    if not isinstance(arguments, dict):
        return JSONResponse(
            {"error": "Arguments must be a JSON object"}, status_code=400
        )
    return _run_tool(tool_name, arguments, SessionKey(run_id, session_id), call_id)


def _run_tool(
    tool_name: str, arguments: dict, key: SessionKey, call_id: str | None
) -> JSONResponse:
    session = sessions.get(key)
    with session.lock:
        try:
            output = _to_json(session.environment.use_tool(tool_name, **arguments))
            status_code, body = 200, output
        except Exception as error:  # the tool refusing the call, in its own words
            status_code, body = 400, {"error": str(error)[:MAX_ERROR_LENGTH]}
    call_log.write(
        {
            "run_id": key.run_id,
            "session_id": key.session_id,
            "call_id": call_id,
            "tool": tool_name,
            "arguments": arguments,
            "status": status_code,
        }
    )
    return JSONResponse(body, status_code=status_code)


@app.get("/runs/{run_id}/sessions/{session_id}/db_hash")
def run_session_db_hash(
    run_id: str, session_id: str, x_api_key: str | None = Header(default=None)
) -> dict:
    """The hash of a session's store, which tau2 compares to the gold store."""
    _require_api_key(x_api_key)
    _require_run_id(run_id)
    return _db_hash(SessionKey(run_id, session_id))


@app.get("/sessions/{session_id}/db_hash")
def default_session_db_hash(
    session_id: str, x_api_key: str | None = Header(default=None)
) -> dict:
    _require_api_key(x_api_key)
    return _db_hash(SessionKey(DEFAULT_RUN_ID, session_id))


def _db_hash(key: SessionKey) -> dict:
    session = sessions.peek(key)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session")
    with session.lock:
        return {
            "run_id": key.run_id,
            "session_id": key.session_id,
            "db_hash": session.environment.get_db_hash(),
        }
