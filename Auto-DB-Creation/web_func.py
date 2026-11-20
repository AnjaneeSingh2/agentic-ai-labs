#!/usr/bin/env python3
"""
web_func.py
=======
OCI Function version of app.py. Same oci.generative_ai_agent_runtime calls
(create_session + chat), triggered by an HTTP request via API Gateway
instead of a Flask route.

POST body:  {"message": "...", "session_id": "<optional>"}
Response:   {"reply": "...", "citations": [...], "session_id": "..."}

Configuration (set as function config vars, see fn config below):
    AGENT_ENDPOINT_ID                 (required)
    OCI_GENAI_AGENT_SERVICE_ENDPOINT  (optional)

Auth: uses the Resource Principal signer (no ~/.oci/config needed). The
function's Dynamic Group must have a policy granting
"use generative-ai-agent-runtime-family" in the agent's compartment.

NOTE on sessions: Function containers are ephemeral and can be recycled
between invocations, so we don't rely on in-process state the way app.py
did. Instead, session_id is created on first message and handed back to
the caller, who must send it on every following message. This keeps the
same OCI-side multi-turn conversation working regardless of which
container instance handles a given request.
"""

import io
import json
import os

import oci
from fdk import response
from oci.generative_ai_agent_runtime import GenerativeAiAgentRuntimeClient
from oci.generative_ai_agent_runtime.models import ChatDetails, CreateSessionDetails

# ---------------------------------------------------------------------------
# Chat history in Autonomous AI Database (ChatRecordsDB, schema AI_VECTOR_DB)
# Config vars: DB_USER, DB_PASSWORD, DB_DSN (e.g. chatrecordsdb_low),
#              WALLET_PASSWORD. Wallet files go in ./wallet next to this file.
# If anything is missing or the DB is down, the chatbot still answers.
# ---------------------------------------------------------------------------
import logging
from datetime import timezone

try:
    import oracledb
    oracledb.defaults.fetch_lobs = False
except ImportError:
    oracledb = None

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_DSN = os.getenv("DB_DSN")
WALLET_PASSWORD = os.getenv("WALLET_PASSWORD")
WALLET_DIR = os.path.join(os.path.dirname(__file__), "wallet")
_pool = None
_log = logging.getLogger()


def _get_pool():
    global _pool
    if _pool is None:
        if not (oracledb and DB_USER and DB_PASSWORD and DB_DSN):
            return None
        kw = {}
        if os.path.isdir(WALLET_DIR):
            kw = dict(config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
                      wallet_password=WALLET_PASSWORD)
        _pool = oracledb.create_pool(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN,
                                     min=0, max=2, increment=1, **kw)
    return _pool


def _save_turn(chat_id, title, session_id, question, answer, citations):
    if not chat_id:
        return
    try:
        pool = _get_pool()
        if not pool:
            return
        with pool.acquire() as c, c.cursor() as cur:
            cur.execute(
                """MERGE INTO chats t USING (SELECT :cid id FROM dual) s ON (t.chat_id = s.id)
                   WHEN MATCHED THEN UPDATE SET agent_session_id = :sid, updated_at = SYSTIMESTAMP
                   WHEN NOT MATCHED THEN INSERT (chat_id, title, agent_session_id)
                        VALUES (:cid, :title, :sid)""",
                dict(cid=chat_id, sid=session_id, title=(title or question)[:500]))
            cur.setinputsizes(None, None, oracledb.DB_TYPE_CLOB, None)
            cur.executemany(
                "INSERT INTO chat_messages (chat_id, role, content, citations) VALUES (:1, :2, :3, :4)",
                [[chat_id, "you", question, None],
                 [chat_id, "agent", answer, json.dumps(citations or [])]])
            c.commit()
    except Exception as e:  # never break the chat because of history
        _log.warning("chat history save failed: %s", e)


def _ms(ts):
    return int(ts.replace(tzinfo=timezone.utc).timestamp() * 1000) if ts else 0


def _history_action(ctx, body):
    action = body.get("action")
    try:
        pool = _get_pool()
        if not pool:
            return _json_response(ctx, 200, {"chats": [], "history": "disabled"})
        with pool.acquire() as c, c.cursor() as cur:
            if action == "delete":
                cur.execute("DELETE FROM chats WHERE chat_id = :1", [body.get("chat_id")])
                c.commit()
                return _json_response(ctx, 200, {"deleted": body.get("chat_id")})
            cur.execute("""SELECT chat_id, title, agent_session_id, updated_at FROM chats
                           ORDER BY updated_at DESC FETCH FIRST 50 ROWS ONLY""")
            chats, order = {}, []
            for cid, title, sid, upd in cur:
                chats[cid] = {"id": cid, "title": title, "sessionId": sid,
                              "updated": _ms(upd), "messages": []}
                order.append(cid)
            if order:
                binds = ",".join(":%d" % (i + 1) for i in range(len(order)))
                cur.execute("SELECT chat_id, role, content, citations FROM chat_messages "
                            "WHERE chat_id IN (%s) ORDER BY created_at, msg_id" % binds, order)
                for cid, role, content, cits in cur:
                    if isinstance(cits, str):
                        cits = json.loads(cits)
                    chats[cid]["messages"].append(
                        {"who": role, "text": content or "", "citations": cits or []})
            return _json_response(ctx, 200, {"chats": [chats[i] for i in order]})
    except Exception as e:
        _log.warning("chat history read failed: %s", e)
        return _json_response(ctx, 200, {"chats": [], "history": "error"})


AGENT_ENDPOINT_ID = os.getenv("AGENT_ENDPOINT_ID", "")
SERVICE_ENDPOINT = os.getenv("OCI_GENAI_AGENT_SERVICE_ENDPOINT")

# Reused across warm invocations of the same container (best-effort cache,
# not relied on for correctness -- session_id round-trips through the client).
_client = None


def _get_client() -> GenerativeAiAgentRuntimeClient:
    global _client
    if _client is None:
        signer = oci.auth.signers.get_resource_principals_signer()
        kwargs = {"retry_strategy": oci.retry.DEFAULT_RETRY_STRATEGY}
        if SERVICE_ENDPOINT:
            kwargs["service_endpoint"] = SERVICE_ENDPOINT
        _client = GenerativeAiAgentRuntimeClient(config={}, signer=signer, **kwargs)
    return _client


def _create_session(client: GenerativeAiAgentRuntimeClient) -> str:
    try:
        details = CreateSessionDetails(
            display_name="web-session",
            idle_timeout_in_seconds=3600,
        )
    except TypeError:
        details = CreateSessionDetails(display_name="web-session")
    session = client.create_session(
        create_session_details=details,
        agent_endpoint_id=AGENT_ENDPOINT_ID,
    )
    return session.data.id


def _extract_text_and_citations(message_content):
    text = getattr(message_content, "text", None)
    if text is None:
        text = str(message_content)
    citations = getattr(message_content, "citations", None) or []
    formatted = []
    for c in citations:
        source_title = getattr(c, "source_title", None) or getattr(c, "title", None) or "unknown"
        source_location = getattr(c, "source_location", None)
        url = getattr(source_location, "url", None) if source_location else None
        formatted.append({"title": source_title, "url": url})
    return text, formatted


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",  # tighten to your actual page's origin in production
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _json_response(ctx, status_code, payload):
    return response.Response(
        ctx,
        status_code=status_code,
        response_data=json.dumps(payload),
        headers={"Content-Type": "application/json", **CORS_HEADERS},
    )


_INDEX_HTML_PATH = os.path.join(os.path.dirname(__file__), "index.html")
_index_html_cache = None


def _load_index_html():
    global _index_html_cache
    if _index_html_cache is None:
        with open(_INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            _index_html_cache = f.read()
    return _index_html_cache


def handler(ctx, data: io.BytesIO = None):
    method = ctx.Method()
    path = ctx.RequestURL() or "/"

    # Browser preflight for cross-origin POST with a JSON body.
    if method == "OPTIONS":
        return response.Response(ctx, status_code=204, response_data="", headers=CORS_HEADERS)

    # Serve the page itself.
    if method == "GET" and (path.endswith("/") or path.endswith("/index.html")):
        try:
            html = _load_index_html()
        except FileNotFoundError:
            return _json_response(ctx, 500, {"error": "index.html not found in function package."})
        return response.Response(
            ctx,
            status_code=200,
            response_data=html,
            headers={"Content-Type": "text/html", **CORS_HEADERS},
        )

    # Everything past this point is the chat API and expects POST.
    if method != "POST":
        return _json_response(ctx, 404, {"error": "not found"})

    if not AGENT_ENDPOINT_ID:
        return _json_response(ctx, 500, {"error": "AGENT_ENDPOINT_ID is not set on the function."})

    try:
        raw = data.getvalue() if data else b""
        body = json.loads(raw) if raw else {}
    except Exception:
        body = {}

    question = (body.get("message") or "").strip()
    session_id = body.get("session_id")
    chat_id = body.get("chat_id")
    if body.get("action") in ("list", "delete"):
        return _history_action(ctx, body)

    if not question:
        return _json_response(ctx, 400, {"error": "Empty message."})

    try:
        client = _get_client()

        if not session_id:
            session_id = _create_session(client)

        chat_response = client.chat(
            agent_endpoint_id=AGENT_ENDPOINT_ID,
            chat_details=ChatDetails(
                user_message=question,
                session_id=session_id,
                should_stream=False,
            ),
        )
        text, citations = _extract_text_and_citations(chat_response.data.message.content)
        _save_turn(chat_id, body.get("title"), session_id, question, text, citations)
        return _json_response(ctx, 200, {"reply": text, "citations": citations, "session_id": session_id})

    except oci.exceptions.ServiceError as e:
        # Session likely died (idle timeout / invalid) -- tell the client to
        # drop it so the *next* request creates a fresh one, since we can't
        # retry transparently without knowing whether the message was applied.
        return _json_response(
            ctx,
            502,
            {
                "error": f"OCI service error ({e.status} {e.code}): {e.message}",
                "session_expired": e.status in (400, 404),
            },
        )
    except oci.exceptions.RequestException as e:
        return _json_response(ctx, 502, {"error": f"Network/request error: {e}"})
