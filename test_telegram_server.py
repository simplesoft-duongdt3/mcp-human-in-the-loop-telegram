"""Tests for telegram_server.py (task 0077: approval-history improvements).

Unit tests cover the pure builders/log helpers (no network). Integration
tests mock the Telegram Bot API via a fake httpx.AsyncClient.
"""
import asyncio
import json
import os

import pytest

import telegram_server as ts


# ─────────────────────────── fakes ───────────────────────────────────────────

class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload) if status_code != 200 else ""

    def json(self):
        return self.payload


class FakeAsyncClient:
    """Queue-driven fake: each `get` pops the next response from `get_queue`
    (defaults to empty). `post` returns `post_response` (or a default ok
    sendMessage response) and records the call."""

    def __init__(self, get_queue=None, post_response=None):
        self.get_queue = list(get_queue or [])
        self.post_response = post_response
        self.calls = []  # (method, url, kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if self.get_queue:
            return self.get_queue.pop(0)
        return FakeResponse({"ok": True, "result": []})

    async def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if self.post_response is not None:
            return self.post_response
        return FakeResponse({"ok": True, "result": {"message_id": 42}})


@pytest.fixture
def fake_http(monkeypatch):
    """Install a fake httpx.AsyncClient and return a factory to configure it."""
    current = {}

    def install(get_queue=None, post_response=None):
        client = FakeAsyncClient(get_queue=get_queue, post_response=post_response)
        current["client"] = client
        monkeypatch.setattr(ts.httpx, "AsyncClient", lambda *a, **k: client)
        return client

    install()
    return install, current


@pytest.fixture
def chat_id(monkeypatch):
    async def _fake_chat_id():
        return "12345"
    monkeypatch.setattr(ts, "get_chat_id", _fake_chat_id)
    return "12345"


@pytest.fixture
def tmp_log(monkeypatch, tmp_path):
    log = tmp_path / "hitl.jsonl"
    monkeypatch.setattr(ts, "_log_path", lambda: str(log))
    return str(log)


# ─────────────────────────── unit: builders ───────────────────────────────

class TestBuilders:
    def test_resolved_keeps_question_and_context(self):
        text = ts.build_resolved_text(
            "Approve task 0077?", "Task 0077 · Phase A", "Yes", "button", "2026-08-06 19:00:00 +0700"
        )
        assert "✅ **Resolved**" in text
        assert "Task 0077 · Phase A" in text
        assert "📝 Approve task 0077?" in text
        assert "Decision: Yes (button)" in text
        assert "2026-08-06 19:00:00 +0700" in text

    def test_resolved_without_context(self):
        text = ts.build_resolved_text("Q?", "", "No", "typed", "ts")
        assert " — " not in text
        assert "Task " not in text

    def test_resolved_escapes_markdown(self):
        text = ts.build_resolved_text("use task_id?", "", "No, rework 03_impl_plan", "typed", "ts")
        assert "task\\_id" in text
        assert "\\_" in text

    def test_resolved_truncates_long_question(self):
        long_q = "x" * 5000
        text = ts.build_resolved_text(long_q, "", "Yes", "button", "ts")
        assert len(text) <= 4096
        assert text.endswith(")") and "…" in text

    def test_resolved_short_question_verbatim(self):
        q = "Approve?"
        text = ts.build_resolved_text(q, "", "Yes", "button", "ts")
        assert f"📝 {q}" in text
        assert "…" not in text

    def test_timeout_preserves_question(self):
        text = ts.build_timeout_text("Approve 0077?", "Task 0077 · Phase A", 15, "ts")
        assert "⏱️ **Timed out**" in text
        assert "no response in 15s" in text
        assert "📝 Approve 0077?" in text
        assert "Decision:" not in text

    def test_timeout_photo_caption_limit(self):
        text = ts.build_timeout_text("x" * 5000, "", 15, "ts", max_len=ts.CAPTION_LIMIT)
        assert len(text) <= ts.CAPTION_LIMIT

    def test_long_typed_decision_truncated(self):
        text = ts.build_resolved_text(
            "Q?", "", "d" * 3000, "typed", "ts", max_len=ts.CAPTION_LIMIT
        )
        assert len(text) <= ts.CAPTION_LIMIT
        assert "Decision: ddd" in text  # question preserved, decision tail cut

    def test_context_with_underscore_escaped(self):
        text = ts.build_resolved_text("Q?", "Task 0077_final", "Yes", "button", "ts")
        assert "0077\_final" in text
        assert "0077_final" not in text


class TestMdEscape:
    @pytest.mark.parametrize("char", ["_", "*", "`", "[", "]"])
    def test_escapes_specials(self, char):
        assert ts._md_escape(f"a{char}b") == f"a\\{char}b"

    def test_plain_text_unchanged(self):
        assert ts._md_escape("plain text 123") == "plain text 123"


# ─────────────────────────── unit: audit log ──────────────────────────────

class TestLog:
    def test_log_path_default(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert ts._log_path() == str(tmp_path / ".config" / "kilo" / "telegram-hitl.log.jsonl")

    def test_log_path_env_override(self, monkeypatch, tmp_path):
        p = tmp_path / "custom.jsonl"
        monkeypatch.setenv("TELEGRAM_HITL_LOG_PATH", str(p))
        assert ts._log_path() == str(p)

    def test_append_creates_dir_and_mode(self, tmp_log):
        ts._log_append({"status": "pending", "x": 1})
        assert os.path.exists(tmp_log)
        assert (os.stat(tmp_log).st_mode & 0o777) == 0o600

    def test_append_coerces_non_serializable(self, tmp_log):
        ts._log_append({"status": "pending", "meta": {"s": {"not-json"}}})
        with open(tmp_log, encoding="utf-8") as f:
            row = json.loads(f.readline())
        assert row["meta"] == {"s": "{'not-json'}"} or isinstance(row["meta"]["s"], str)

    def test_append_is_append_only(self, tmp_log):
        ts._log_append({"status": "pending"})
        ts._log_append({"status": "resolved", "decision": "Yes"})
        with open(tmp_log, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f if l.strip()]
        assert [r["status"] for r in rows] == ["pending", "resolved"]

    def test_snapshot_schema_per_status(self):
        base = dict(chat_id="1", message_id=2, question="q", options=["A"], task_id="0077", phase="A", metadata={})
        pending = ts._log_snapshot("pending", **base)
        assert "decision" not in pending and "via" not in pending
        resolved = ts._log_snapshot("resolved", **base, decision="A", via="button")
        assert resolved["decision"] == "A" and resolved["via"] == "button"
        timeout = ts._log_snapshot("timeout", **base)
        assert "decision" not in timeout and "via" not in timeout


class TestHistory:
    def _write(self, tmp_log, rows):
        with open(tmp_log, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def _row(self, mid, status, task_id="0077", decision=None, via=None, ts_="2026-08-06 19:00:00 +0700"):
        r = {"ts": ts_, "status": status, "task_id": task_id, "phase": "A",
             "question": "Approve the spec?", "options": [], "message_id": mid,
             "chat_id": "1", "metadata": {}}
        if decision is not None:
            r["decision"] = decision
        if via is not None:
            r["via"] = via
        return r

    @pytest.mark.asyncio
    async def test_dedupe_terminal_wins(self, tmp_log):
        self._write(tmp_log, [self._row(1, "pending"), self._row(1, "resolved", decision="Yes", via="button")])
        out = await ts.get_telegram_history()
        assert "✅ Yes (button)" in out
        assert "⏳ pending" not in out
        assert out.count("Approve the spec?") == 1

    @pytest.mark.asyncio
    async def test_pending_only(self, tmp_log):
        self._write(tmp_log, [self._row(1, "pending")])
        out = await ts.get_telegram_history()
        assert "⏳ pending" in out

    @pytest.mark.asyncio
    async def test_task_id_filter_matches_empty(self, tmp_log):
        self._write(tmp_log, [self._row(1, "resolved", task_id="0077", decision="Yes", via="button"),
                              self._row(2, "resolved", task_id="", decision="No", via="typed"),
                              self._row(3, "resolved", task_id="9999", decision="Z9", via="typed")])
        out = await ts.get_telegram_history(task_id="0077")
        assert "Yes (button)" in out and "No (typed)" in out  # 0077 + legacy empty both match
        assert "Z9" not in out  # non-matching record excluded

    @pytest.mark.asyncio
    async def test_limit_rules(self, tmp_log):
        rows = [self._row(i, "resolved", decision="Yes", via="button", ts_=f"2026-08-06 19:{i:02d}:00 +0700") for i in range(3)]
        self._write(tmp_log, rows)
        out0 = await ts.get_telegram_history(limit=0)
        assert out0.count("\n") == 3  # header + 3 rows (default 20 on 3 rows -> all 3)
        out100 = await ts.get_telegram_history(limit=100)
        assert "3 record(s)" in out100
        # newest first: 19:02 first
        first_line = out100.splitlines()[1]
        assert "19:02" in first_line

    @pytest.mark.asyncio
    async def test_limit_max_clamp(self, tmp_log):
        rows = [self._row(i, "resolved", decision="Yes", via="button", ts_=f"2026-08-06 19:{i % 60:02d}:00 +0700") for i in range(105)]
        self._write(tmp_log, rows)
        out = await ts.get_telegram_history(limit=500)
        assert "100 record(s)" in out  # clamped at max 100

    @pytest.mark.asyncio
    async def test_missing_log(self, tmp_log):
        out = await ts.get_telegram_history()
        assert "No approval records" in out

    @pytest.mark.asyncio
    async def test_question_truncated_to_80(self, tmp_log):
        self._write(tmp_log, [self._row(1, "resolved", decision="Yes", via="button") | {"question": "q" * 120}])
        out = await ts.get_telegram_history()
        assert "…" in out


# ─────────────────────────── integration (mocked HTTP) ────────────────────

@pytest.mark.asyncio
async def test_poll_button_path(fake_http, chat_id, tmp_log, monkeypatch):
    install, _ = fake_http
    client = install(get_queue=[
        FakeResponse({"ok": True, "result": [{"update_id": 10}]}),  # initial offset
        FakeResponse({"ok": True, "result": [
            {"update_id": 11, "callback_query": {"id": "c1", "from": {"id": 1},
             "message": {"chat": {"id": chat_id}}, "data": "Yes"}}
        ]}),
    ])
    result = await ts.poll_for_response(chat_id, 42, timeout_seconds=2, question="Approve?",
                                        context="Task 0077 · Phase A", task_id="0077", phase="A",
                                        options=["Yes", "No"])
    assert result == "Yes"
    edits = [c for c in client.calls if c[0] == "post" and "editMessageText" in c[1]]
    assert edits, "editMessageText must be called"
    payload = edits[-1][2]["json"]
    assert payload["reply_markup"] == {"inline_keyboard": []}
    assert "Approve?" in payload["text"] and "Decision: Yes (button)" in payload["text"]
    assert "Task 0077 · Phase A" in payload["text"]
    with open(tmp_log, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    assert rows[-1]["status"] == "resolved" and rows[-1]["via"] == "button" and rows[-1]["decision"] == "Yes"
    assert rows[-1]["options"] == ["Yes", "No"]


@pytest.mark.asyncio
async def test_poll_typed_path(fake_http, chat_id, tmp_log):
    install, _ = fake_http
    client = install(get_queue=[
        FakeResponse({"ok": True, "result": [{"update_id": 10}]}),
        FakeResponse({"ok": True, "result": [
            {"update_id": 11, "message": {"chat": {"id": chat_id}, "text": "No, rework it"}}
        ]}),
    ])
    result = await ts.poll_for_response(chat_id, 42, timeout_seconds=2, question="Approve?", context="")
    assert result == "No, rework it"
    edits = [c for c in client.calls if c[0] == "post" and "editMessageText" in c[1]]
    assert "Decision: No, rework it (typed)" in edits[-1][2]["json"]["text"]


@pytest.mark.asyncio
async def test_poll_custom_button_then_typed(fake_http, chat_id, tmp_log):
    install, _ = fake_http
    client = install(get_queue=[
        FakeResponse({"ok": True, "result": [{"update_id": 10}]}),
        FakeResponse({"ok": True, "result": [
            {"update_id": 11, "callback_query": {"id": "c1", "from": {"id": 1},
             "message": {"chat": {"id": chat_id}}, "data": "__CUSTOM__"}}
        ]}),
        FakeResponse({"ok": True, "result": [
            {"update_id": 12, "message": {"chat": {"id": chat_id}, "text": "custom answer"}}
        ]}),
    ])
    result = await ts.poll_for_response(chat_id, 42, timeout_seconds=6, question="Approve?")
    assert result == "custom answer"  # __CUSTOM__ never returned as the decision
    acks = [c for c in client.calls if c[0] == "post" and "answerCallbackQuery" in c[1]]
    assert len(acks) == 1
    edits = [c for c in client.calls if c[0] == "post" and "editMessageText" in c[1]]
    assert "Decision: custom answer (typed)" in edits[-1][2]["json"]["text"]


@pytest.mark.asyncio
async def test_poll_timeout_marks_message(fake_http, chat_id, tmp_log):
    install, _ = fake_http
    client = install(get_queue=[
        FakeResponse({"ok": True, "result": [{"update_id": 10}]}),
        FakeResponse({"ok": True, "result": []}),  # every poll returns nothing
    ])
    result = await ts.poll_for_response(chat_id, 42, timeout_seconds=2, question="Approve?", context="Task 0077")
    assert result.startswith("Timeout:")
    edits = [c for c in client.calls if c[0] == "post" and "editMessageText" in c[1]]
    assert "Timed out" in edits[-1][2]["json"]["text"]
    with open(tmp_log, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    assert rows[-1]["status"] == "timeout"


@pytest.mark.asyncio
async def test_edit_retries_without_parse_mode(fake_http, chat_id):
    install, _ = fake_http
    client = install(post_response=FakeResponse({"ok": False, "description": "can't parse entities"}, status_code=400))
    ok = await ts._edit_message(chat_id, 1, "text with _")
    edits = [c for c in client.calls if c[0] == "post"]
    assert len(edits) == 2
    assert "parse_mode" not in edits[1][2]["json"]


@pytest.mark.asyncio
async def test_ask_human_metadata_not_sent(fake_http, chat_id, tmp_log, monkeypatch):
    install, _ = fake_http
    client = install(get_queue=[
        FakeResponse({"ok": True, "result": [{"update_id": 10}]}),
        FakeResponse({"ok": True, "result": []}),
    ])
    monkeypatch.setattr(ts, "poll_for_response", lambda *a, **k: asyncio.sleep(0) or "done")
    await ts.ask_human("Approve?", options=["Yes"], task_id="0077", phase="A",
                       metadata={"secret": "value"})
    send = [c for c in client.calls if c[0] == "post" and "sendMessage" in c[1]][0][2]["json"]
    assert "🤖 **Kilo has a question:** — Task 0077 · Phase A" in send["text"]
    assert "secret" not in json.dumps(send)
    with open(tmp_log, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    assert rows[-1]["metadata"] == {"secret": "value"}


@pytest.mark.asyncio
async def test_ask_human_no_options_typed_resolution(fake_http, chat_id, tmp_log, monkeypatch):
    install, _ = fake_http
    client = install(get_queue=[
        FakeResponse({"ok": True, "result": [{"update_id": 10}]}),
        FakeResponse({"ok": True, "result": [
            {"update_id": 11, "message": {"chat": {"id": chat_id}, "text": "ok"}}
        ]}),
    ])
    result = await ts.ask_human("Just answer:", timeout_seconds=2)
    assert result == "ok"
    send = [c for c in client.calls if c[0] == "post" and "sendMessage" in c[1]][0][2]["json"]
    assert "reply_markup" not in send
    with open(tmp_log, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    assert rows[0]["options"] == [] and rows[1]["via"] == "typed"


@pytest.mark.asyncio
async def test_ask_human_photo_flow(fake_http, chat_id, tmp_log, tmp_path, monkeypatch):
    png = tmp_path / "diagram.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    install, _ = fake_http
    client = install(get_queue=[
        FakeResponse({"ok": True, "result": [{"update_id": 10}]}),
        FakeResponse({"ok": True, "result": [
            {"update_id": 11, "callback_query": {"id": "c1", "from": {"id": 1},
             "message": {"chat": {"id": chat_id}}, "data": "Approve"}}
        ]}),
    ])
    result = await ts.ask_human("Approve the diagram?", options=["Approve"], task_id="0077",
                                phase="A", photo_path=str(png), timeout_seconds=2)
    assert result == "Approve"
    sends = [c for c in client.calls if c[0] == "post" and "sendPhoto" in c[1]]
    assert sends, "sendPhoto must be used when photo_path given"
    assert "photo" in sends[0][2]["files"]
    captions = [c for c in client.calls if c[0] == "post" and "editMessageCaption" in c[1]]
    assert captions, "photo resolutions must edit the caption"
    resolved_caption = captions[-1][2]["json"]["caption"]
    assert "Decision: Approve (button)" in resolved_caption
    assert len(resolved_caption) <= ts.CAPTION_LIMIT
    send_data = [c for c in client.calls if c[0] == "post" and "sendPhoto" in c[1]][0][2]["data"]
    assert len(send_data["caption"]) <= ts.CAPTION_LIMIT  # initial caption too


@pytest.mark.asyncio
async def test_wait_false_then_response(fake_http, chat_id, tmp_log, monkeypatch):
    install, _ = fake_http
    client = install()
    ts.TelegramState.pending = None
    out = await ts.ask_human("Quick?", options=["A", "B"], wait=False, task_id="0077", phase="B")
    assert "Message ID" in out
    assert ts.TelegramState.pending is not None
    assert ts.TelegramState.pending["message_id"] == 42
    # now the user replies; get_telegram_response retrieves and marks resolved
    client.get_queue.append(FakeResponse({"ok": True, "result": [
        {"update_id": 50, "message": {"chat": {"id": chat_id}, "text": "B"}}
    ]}))
    answer = await ts.get_telegram_response()
    assert answer == "B"
    edits = [c for c in client.calls if c[0] == "post" and "editMessageText" in c[1]]
    assert "Decision: B (typed)" in edits[-1][2]["json"]["text"]
    assert ts.TelegramState.pending is None
    with open(tmp_log, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    assert [r["status"] for r in rows] == ["pending", "resolved"]


@pytest.mark.asyncio
async def test_wait_false_overwrite(fake_http, chat_id, tmp_log):
    install, _ = fake_http
    ts.TelegramState.pending = None
    await ts.ask_human("Q1?", wait=False)
    first = ts.TelegramState.pending["message_id"]
    await ts.ask_human("Q2?", wait=False)
    assert ts.TelegramState.pending["message_id"] == first  # same fake id, slot replaced
    assert ts.TelegramState.pending["question"] == "Q2?"  # slot content replaced


@pytest.mark.asyncio
async def test_send_telegram_photo_tool_happy(fake_http, chat_id, tmp_path, monkeypatch):
    install, _ = fake_http
    client = install()
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    out = await ts.send_telegram_photo(str(png), caption="E2E dashboard")
    assert "sent" in out.lower()
    sends = [c for c in client.calls if c[0] == "post" and "sendPhoto" in c[1]]
    assert len(sends) == 1
    caption = sends[0][2]["data"]["caption"]
    assert "**Kilo image:**" in caption  # tool's own bold markup NOT escaped
    assert "E2E dashboard" in caption

    out2 = await ts.send_telegram_photo(str(png), caption="run_1 complete")
    sends2 = [c for c in client.calls if c[0] == "post" and "sendPhoto" in c[1]]
    assert "run\_1 complete" in sends2[-1][2]["data"]["caption"]  # user text escaped


@pytest.mark.asyncio
async def test_send_telegram_photo_tool_missing_file(fake_http, chat_id):
    install, _ = fake_http
    install()
    out = await ts.send_telegram_photo("/nonexistent/nope.png", caption="x")
    assert "not found" in out
    assert ts.httpx.AsyncClient().calls == []  # no HTTP call made


@pytest.mark.asyncio
async def test_send_telegram_photo_tool_upload_error(fake_http, chat_id, tmp_path, monkeypatch):
    install, _ = fake_http
    install(post_response=FakeResponse({"ok": False, "description": "bad"}, status_code=400))
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    out = await ts.send_telegram_photo(str(png), caption="x")
    assert "Error sending photo" in out


@pytest.mark.asyncio
async def test_get_response_mark_as_read_false_no_resolve(fake_http, chat_id, tmp_log):
    install, _ = fake_http
    client = install()
    ts.TelegramState.pending = None
    await ts.ask_human("Quick?", wait=False)
    assert ts.TelegramState.pending is not None
    client.get_queue.append(FakeResponse({"ok": True, "result": [
        {"update_id": 50, "message": {"chat": {"id": chat_id}, "text": "B"}}
    ]}))
    answer = await ts.get_telegram_response(mark_as_read=False)
    assert answer == "B"
    assert ts.TelegramState.pending is not None  # not consumed
    assert not [c for c in client.calls if c[0] == "post" and "editMessageText" in c[1]]
    with open(tmp_log, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    assert [r["status"] for r in rows] == ["pending"]  # no resolved row yet


@pytest.mark.asyncio
async def test_wait_false_with_photo_resolves_caption(fake_http, chat_id, tmp_log, tmp_path):
    png = tmp_path / "d.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    install, _ = fake_http
    client = install()
    ts.TelegramState.pending = None
    await ts.ask_human("See diagram?", options=["Ok"], wait=False, photo_path=str(png))
    assert ts.TelegramState.pending["is_photo"] is True
    client.get_queue.append(FakeResponse({"ok": True, "result": [
        {"update_id": 50, "message": {"chat": {"id": chat_id}, "text": "Ok"}}
    ]}))
    answer = await ts.get_telegram_response()
    assert answer == "Ok"
    captions = [c for c in client.calls if c[0] == "post" and "editMessageCaption" in c[1]]
    assert captions, "photo pending must resolve via editMessageCaption"
    assert "Decision: Ok (typed)" in captions[-1][2]["json"]["caption"]
    assert ts.TelegramState.pending is None


@pytest.mark.asyncio
async def test_history_skips_corrupt_lines(tmp_log):
    with open(tmp_log, "w", encoding="utf-8") as f:
        f.write("not json at all\n")
        f.write("[1, 2, 3]\n")  # valid JSON but not a dict
        f.write('{"ts": "2026-08-06 19:00:00 +0700", "status": "resolved", "task_id": "0077",'
                ' "phase": "A", "question": "q", "options": [], "message_id": 1,'
                ' "chat_id": "1", "metadata": {}, "decision": "Yes", "via": "button"}\n')
        f.write('{"ts": 12345, "status": "resolved", "task_id": "0077", "phase": "A",'
                ' "question": "q2", "options": [], "message_id": 2,'
                ' "chat_id": "1", "metadata": {}, "decision": "No", "via": "typed"}\n')
    out = await ts.get_telegram_history()
    assert "not json" not in out
    assert "✅ Yes (button)" in out and "✅ No (typed)" in out  # int ts coerced, no crash


@pytest.mark.asyncio
async def test_send_question_photo_missing_file(fake_http, chat_id):
    install, _ = fake_http
    install()
    info = await ts._send_question_photo(chat_id, "/nonexistent/nope.png", "Q?", options=None)
    assert info["success"] is False


@pytest.mark.asyncio
async def test_history_line_format_no_double_task(tmp_log):
    import telegram_server as ts
    row = {"ts": "2026-08-06 19:00:00 +0700", "status": "resolved", "task_id": "0077", "phase": "A",
           "question": "Approve the spec?", "options": [], "message_id": 1, "chat_id": "1", "metadata": {},
           "decision": "Yes", "via": "button"}
    with open(tmp_log, "w", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    out = await ts.get_telegram_history()
    line = out.splitlines()[1]
    assert "Task Task" not in line
    assert line.startswith("[19:00] Task 0077 · Phase A → ✅ Yes (button) — ")


@pytest.mark.asyncio
async def test_list_messages_filter_then_slice_and_edited(fake_http, chat_id):
    install, _ = fake_http
    other = {"id": 999}
    client = install(get_queue=[FakeResponse({"ok": True, "result": [
        {"update_id": 1, "message": {"chat": {"id": other}, "text": "other chat"}},
        {"update_id": 2, "message": {"chat": {"id": chat_id}, "text": "question?"}},
        {"update_id": 3, "edited_message": {"chat": {"id": chat_id}, "text": "✅ Resolved", "date": 0}},
    ]})])
    out = await ts.list_telegram_messages(limit=10)
    assert "[edited] ✅ Resolved" in out
    assert "other chat" not in out
