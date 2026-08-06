import asyncio
import datetime
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

# Load environment variables (or hardcode your token below)
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# You can hardcode your Chat ID here if you want security,
# or the bot will try to auto-detect the last person who messaged it.
ALLOWED_USER_ID = os.getenv("TELEGRAM_USER_ID")

# Initialize MCP Server
mcp = FastMCP("Telegram Human Loop")

# Telegram API Base URL
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# editMessageText / editMessageCaption limits
TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024

# Telegram legacy Markdown specials that must be escaped in user-controlled text.
_ESCAPE_MAP = str.maketrans({"_": "\\_", "*": "\\*", "`": "\\`", "[": "\\[", "]": "\\]"})


def _md_escape(text: str) -> str:
    """Escape Telegram legacy-Markdown specials so the text cannot break parsing."""
    return text.translate(_ESCAPE_MAP)


def _now_iso() -> str:
    """Local timestamp, e.g. 2026-08-06 19:00:00 +0700"""
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def _log_path() -> str:
    """Audit log location: TELEGRAM_HITL_LOG_PATH env override, else
    ~/.config/kilo/telegram-hitl.log.jsonl"""
    env = os.environ.get("TELEGRAM_HITL_LOG_PATH")
    if env:
        return env
    return str(Path.home() / ".config" / "kilo" / "telegram-hitl.log.jsonl")


def _log_append(record: dict) -> None:
    """Append one JSONL snapshot to the audit log. Best-effort: never fail the
    approval flow when logging breaks; file created with mode 0o600 so the
    umask cannot weaken it."""
    path = _log_path()
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        print(f"WARN: failed to append HITL audit log: {e}")


def _log_snapshot(
    status: str,
    chat_id: str,
    message_id: int,
    question: str,
    options: list,
    task_id: str,
    phase: str,
    metadata: dict,
    decision: str = None,
    via: str = None,
) -> dict:
    """Build one full-snapshot JSONL record per the 02_tech_design schema."""
    record = {
        "ts": _now_iso(),
        "status": status,
        "task_id": task_id or "",
        "phase": phase or "",
        "question": question,
        "options": list(options or []),
        "message_id": message_id,
        "chat_id": str(chat_id),
        "metadata": metadata or {},
    }
    if decision is not None:
        record["decision"] = decision
    if via is not None:
        record["via"] = via
    return record


def _build_context(task_id: str, phase: str) -> str:
    """Pre-built context label: 'Task 0077 · Phase A' / 'Task 0077' / ''."""
    if not task_id:
        return ""
    if phase:
        return f"Task {task_id} · Phase {phase}"
    return f"Task {task_id}"


def _truncate_question(question: str, budget: int) -> str:
    """Truncate the question tail with … so the full message fits Telegram limits."""
    if len(question) <= budget:
        return question
    if budget <= 0:
        return ""
    return question[: budget - 1] + "…"


def build_resolved_text(question, context, answer, via, timestamp, max_len=TEXT_LIMIT) -> str:
    """Resolved-message text: keeps the question, context, decision and time.
    The question gets the first budget share, then the decision the rest, so
    the result never exceeds max_len (typed answers can be long)."""
    ctx = _md_escape(context) if context else ""
    ctx_part = f" — {ctx}" if ctx else ""
    prefix = f"✅ **Resolved**{ctx_part}\n\n📝 "
    tail = f"\n\n⏱ {timestamp}\n💬 Decision: "
    via_part = f" ({via})"
    q = _md_escape(question)
    a = _md_escape(answer)
    rest = max_len - len(prefix) - len(tail) - len(via_part)
    q = _truncate_question(q, max(rest - len(a), 0))
    remaining = max_len - len(prefix) - len(q) - len(tail) - len(via_part)
    a = _truncate_question(a, remaining)
    return prefix + q + tail + a + via_part


def build_timeout_text(question, context, timeout_secs, timestamp, max_len=TEXT_LIMIT) -> str:
    """Timed-out message text: question preserved, no decision."""
    ctx = _md_escape(context) if context else ""
    ctx = f" · {ctx}" if ctx else ""
    prefix = f"⏱️ **Timed out** — no response in {timeout_secs}s{ctx}\n\n📝 "
    suffix = f"\n\n⏱ {timestamp}"
    q = _md_escape(question)
    budget = max_len - len(prefix) - len(suffix)
    return prefix + _truncate_question(q, max(budget, 0)) + suffix


async def _edit_message(chat_id: str, message_id: int, text: str, is_photo: bool = False) -> bool:
    """Edit a sent message to its resolved/timed-out text. Photo messages use
    editMessageCaption (caption limit 1024); text messages use
    editMessageText (4096). Buttons are always removed. On a Markdown parse
    error the edit is retried without parse_mode (AC13); other failures are
    logged and non-fatal."""
    endpoint = f"{TELEGRAM_API}/editMessageCaption" if is_photo else f"{TELEGRAM_API}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": []},
    }
    payload["caption" if is_photo else "text"] = text
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(endpoint, json=payload)
            if resp.status_code == 200:
                return True
            if resp.status_code == 400:
                # Retry without parse_mode — unbalanced Markdown in the
                # question/decision would otherwise fail the edit silently.
                retry = dict(payload)
                retry.pop("parse_mode", None)
                resp = await client.post(endpoint, json=retry)
                if resp.status_code == 200:
                    return True
            print(f"WARN: {endpoint} failed: {resp.text}")
            return False
        except Exception as e:
            print(f"WARN: {endpoint} error: {e}")
            return False


class TelegramState:
    """Tracks state across tool calls to avoid re-processing messages"""
    last_processed_update_id: int = 0
    # Single-slot pending question for the wait=False flow (newest wins).
    pending: dict = None

    @classmethod
    def get_last_update_id(cls):
        """Get the current last update ID (0 means no messages processed yet)"""
        return cls.last_processed_update_id

    @classmethod
    def update_last_id(cls, update_id: int):
        """Update the last processed update ID"""
        if update_id > cls.last_processed_update_id:
            cls.last_processed_update_id = update_id


async def get_chat_id():
    """Helper to find your Chat ID if not set."""
    if ALLOWED_USER_ID:
        return ALLOWED_USER_ID

    # Try to fetch updates to find the last user who messaged the bot
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{TELEGRAM_API}/getUpdates")
        data = resp.json()
        if data.get('result'):
            # Get the most recent chat ID
            return str(data['result'][-1]['message']['chat']['id'])
    return None


def _mime_for(path: str) -> str:
    """Image content-type guessed from the file extension (PNG/JPEG)."""
    lower = path.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    return "image/png"


def _make_keyboard(options: list, allow_custom: bool) -> dict:
    keyboard = []
    for opt in options:
        keyboard.append([{"text": opt, "callback_data": opt}])
    if allow_custom:
        keyboard.append([{"text": "✏️ Custom answer (type below)", "callback_data": "__CUSTOM__"}])
    return {"inline_keyboard": keyboard}


async def send_telegram_message(
    chat_id: str, text: str, options: list[str] = None, allow_custom: bool = True,
    context_header: str = ""
) -> dict:
    """
    Sends a message to Telegram and returns the message info.

    Args:
        chat_id: Telegram chat ID to send to
        text: Message text to send (Markdown-special chars are escaped)
        options: Optional list of button options
        allow_custom: If True and options provided, adds "Custom answer" button
        context_header: Optional 'Task 0077 · Phase A' label appended to the header

    Returns:
        dict with 'success', 'message_id', and optional 'error' keys
    """
    header = f"🤖 **Kilo has a question:** — {_md_escape(context_header)}" if context_header else "🤖 **Kilo has a question:**"
    payload = {
        "chat_id": chat_id,
        "text": f"{header}\n\n{_md_escape(text)}",
        "parse_mode": "Markdown"
    }

    if options:
        payload["reply_markup"] = _make_keyboard(options, allow_custom)

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
            if resp.status_code != 200:
                return {"success": False, "error": resp.text}

            sent_message_id = resp.json()['result']['message_id']
            return {"success": True, "message_id": sent_message_id}
        except Exception as e:
            return {"success": False, "error": str(e)}


async def _send_question_photo(
    chat_id: str, photo_path: str, text: str, options: list[str] = None,
    allow_custom: bool = True, context_header: str = ""
) -> dict:
    """
    Sends a question as a photo message (caption + optional buttons).

    Args:
        chat_id: Telegram chat ID to send to
        photo_path: Local path of the image (PNG/JPEG) to upload
        text: Caption text (Markdown-special chars are escaped)
        options: Optional list of button options
        allow_custom: If True and options provided, adds "Custom answer" button
        context_header: Optional 'Task 0077 · Phase A' label appended to the header

    Returns:
        dict with 'success', 'message_id', and optional 'error' keys
    """
    header = f"🤖 **Kilo has a question:** — {_md_escape(context_header)}" if context_header else "🤖 **Kilo has a question:**"
    caption = f"{header}\n\n{_md_escape(text)}"
    payload = {
        "chat_id": chat_id,
        "caption": _truncate_question(caption, CAPTION_LIMIT),
        "parse_mode": "Markdown",
    }
    if options:
        # multipart form data requires non-primitive values to be JSON strings
        payload["reply_markup"] = json.dumps(_make_keyboard(options, allow_custom), ensure_ascii=False)

    try:
        with open(photo_path, "rb") as f:
            files = {"photo": (os.path.basename(photo_path), f, _mime_for(photo_path))}
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{TELEGRAM_API}/sendPhoto", data=payload, files=files)
        if resp.status_code != 200:
            return {"success": False, "error": resp.text}
        sent_message_id = resp.json()['result']['message_id']
        return {"success": True, "message_id": sent_message_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def poll_for_response(
    chat_id: str, sent_message_id: int, timeout_seconds: int = 180,
    question: str = "", context: str = "", is_photo: bool = False,
    task_id: str = "", phase: str = "", metadata: dict = None,
    options: list[str] = None
) -> str:
    """
    Polls Telegram for a response to a specific message.

    Args:
        chat_id: Telegram chat ID to poll
        sent_message_id: ID of the message we're waiting for a response to
        timeout_seconds: Maximum time to wait
        question: Original question text (for the resolved/timed-out edits)
        context: Pre-built context label ('Task 0077 · Phase A')
        is_photo: True when the pending message is a photo (caption edits)
        task_id/phase/metadata: echoed into the audit log snapshots

    Returns:
        User's response text or timeout message
    """
    max_retries = timeout_seconds // 2  # Poll every 2 seconds
    last_update_id = 0

    # Get initial offset
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{TELEGRAM_API}/getUpdates")
        data = resp.json()
        if data.get('result'):
            last_update_id = data['result'][-1]['update_id']

    print(f"Waiting for reply to message {sent_message_id}...")

    for _ in range(max_retries):
        async with httpx.AsyncClient() as client:
            try:
                # Long polling with 2 second timeout
                resp = await client.get(
                    f"{TELEGRAM_API}/getUpdates",
                    params={"offset": last_update_id + 1, "timeout": 2}
                )
                data = resp.json()

                if not data.get('result'):
                    await asyncio.sleep(2)
                    continue

                for update in data['result']:
                    last_update_id = update['update_id']

                    # Check for Button Click (Callback Query)
                    if 'callback_query' in update:
                        cb = update['callback_query']
                        answer = cb['data']

                        # Check if user clicked "Custom answer" button
                        if answer == "__CUSTOM__":
                            # Acknowledge the button click
                            await client.post(f"{TELEGRAM_API}/answerCallbackQuery", json={
                                "callback_query_id": cb['id'],
                                "text": "Please type your custom answer below"
                            })
                            # Don't return yet - wait for the text message
                            continue

                        # Acknowledge the button click to stop the loading animation
                        await client.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": cb['id']})

                        # Edit the original message to a self-contained resolved text
                        resolved = build_resolved_text(
                            question, context, answer, "button", _now_iso(),
                            max_len=CAPTION_LIMIT if is_photo else TEXT_LIMIT,
                        )
                        await _edit_message(chat_id, sent_message_id, resolved, is_photo)
                        _log_append(_log_snapshot(
                            "resolved", chat_id, sent_message_id, question, options or [],
                            task_id, phase, metadata, decision=answer, via="button",
                        ))

                        # Update state
                        TelegramState.update_last_id(last_update_id)
                        return answer

                    # Check for Text Reply
                    if 'message' in update:
                        msg = update['message']
                        # Accept messages from the authorized user
                        if str(msg['chat']['id']) == str(chat_id):
                            user_text = msg.get('text', '')
                            resolved = build_resolved_text(
                                question, context, user_text, "typed", _now_iso(),
                                max_len=CAPTION_LIMIT if is_photo else TEXT_LIMIT,
                            )
                            await _edit_message(chat_id, sent_message_id, resolved, is_photo)
                            _log_append(_log_snapshot(
                                "resolved", chat_id, sent_message_id, question, options or [],
                                task_id, phase, metadata, decision=user_text, via="typed",
                            ))
                            # Update state
                            TelegramState.update_last_id(last_update_id)
                            return user_text

            except Exception as e:
                print(f"Polling error: {e}")
                await asyncio.sleep(1)

    # Timeout: mark the message resolved (timed-out format) and log it
    timed_out = build_timeout_text(
        question, context, timeout_seconds, _now_iso(),
        max_len=CAPTION_LIMIT if is_photo else TEXT_LIMIT,
    )
    await _edit_message(chat_id, sent_message_id, timed_out, is_photo)
    _log_append(_log_snapshot(
        "timeout", chat_id, sent_message_id, question, options or [],
        task_id, phase, metadata,
    ))
    return "Timeout: User did not respond in time. Please try again or assume a default."


async def get_latest_message(chat_id: str, since_update_id: int = None) -> dict:
    """
    Fetches the most recent message from the user.

    Args:
        chat_id: Telegram chat ID to fetch from
        since_update_id: Only fetch messages after this update ID

    Returns:
        dict with 'text', 'update_id', 'timestamp' or None if no new messages
    """
    async with httpx.AsyncClient() as client:
        try:
            params = {}
            if since_update_id:
                params['offset'] = since_update_id + 1

            resp = await client.get(f"{TELEGRAM_API}/getUpdates", params=params)
            data = resp.json()

            if not data.get('result'):
                return None

            # Find the most recent message from the user
            for update in reversed(data['result']):
                if 'message' in update:
                    msg = update['message']
                    if str(msg['chat']['id']) == str(chat_id):
                        return {
                            'text': msg.get('text') or msg.get('caption') or '[No text content]',
                            'update_id': update['update_id'],
                            'timestamp': msg.get('date', 0)
                        }

                # Also check for callback queries (button clicks)
                if 'callback_query' in update:
                    cb = update['callback_query']
                    if str(cb['message']['chat']['id']) == str(chat_id):
                        return {
                            'text': cb['data'],
                            'update_id': update['update_id'],
                            'timestamp': cb['message'].get('date', 0)
                        }

            return None

        except Exception as e:
            print(f"Error fetching latest message: {e}")
            return None


@mcp.tool()
async def ask_human(
    question: str,
    options: list[str] = None,
    wait: bool = True,
    timeout_seconds: int = 180,
    allow_custom: bool = True,
    task_id: str = "",
    phase: str = "",
    metadata: dict = None,
    photo_path: str = ""
) -> str:
    """
    Sends a question to the user via Telegram (optionally with a diagram photo).

    Args:
        question: The text of the question to ask the user.
        options: Optional list of short strings (e.g. ["Yes", "No"]) to show as buttons.
                 If provided and allow_custom=True, a "Custom answer" button is added.
        wait: If True (default), blocks until response received or timeout.
              If False, sends question and returns immediately.
        timeout_seconds: Maximum time to wait for response (only used if wait=True).
                         Default 180 (3 minutes) — matches the MCP client timeout.
        allow_custom: If True (default) and options provided, adds a "Custom answer" button
                      allowing the user to type their own response instead of clicking a button.
        task_id: Optional task number (e.g. "0077") shown in the message header
                 and recorded in the audit log.
        phase: Optional phase label (e.g. "A") shown with the task in the header.
        metadata: Optional dict persisted ONLY in the audit log — never sent to Telegram.
        photo_path: Optional local path of a PNG/JPEG (e.g. a rendered mermaid
                    diagram) to attach as the question photo. Buttons work on the
                    photo message; resolutions edit the caption.

    Returns:
        - If wait=True: The user's answer or timeout message
        - If wait=False: Confirmation message with instructions

    Examples:
        # Blocking mode with buttons and custom answer option
        answer = ask_human("Should I proceed?", options=["Yes", "No"])

        # Approval with task context and rendered diagram
        answer = ask_human(
            "Approve the spec?",
            options=["Approve", "Reject"],
            task_id="0077",
            phase="A",
            photo_path="docs/tasks/0077-.../diagrams/01-01_detail-diagram-01.png",
        )

        # Non-blocking mode with buttons
        ask_human("Which approach?", options=["Option 1", "Option 2"], wait=False)
        # Later: answer = get_telegram_response()
    """
    chat_id = await get_chat_id()
    if not chat_id:
        return "Error: Could not find a Telegram Chat ID. Please message the bot first."

    context = _build_context(task_id, phase)

    # Send the message (photo caption when photo_path given, else text)
    if photo_path:
        message_info = await _send_question_photo(
            chat_id, photo_path, question, options, allow_custom, context_header=context
        )
    else:
        message_info = await send_telegram_message(
            chat_id, question, options, allow_custom, context_header=context
        )

    if not message_info['success']:
        return f"Error sending Telegram message: {message_info.get('error', 'Unknown error')}"

    message_id = message_info['message_id']
    is_photo = bool(photo_path)
    _log_append(_log_snapshot(
        "pending", chat_id, message_id, question, options or [],
        task_id, phase, metadata,
    ))

    # Non-blocking mode: return immediately, remember the pending message
    if not wait:
        TelegramState.pending = {
            "chat_id": chat_id,
            "message_id": message_id,
            "question": question,
            "context": context,
            "is_photo": is_photo,
            "task_id": task_id,
            "phase": phase,
            "metadata": metadata,
            "options": options or [],
        }
        return (
            f"✅ Question sent to Telegram (Message ID: {message_id}).\n\n"
            f"When you've replied, use the get_telegram_response() tool to retrieve your answer."
        )

    # Blocking mode: wait for response
    return await poll_for_response(
        chat_id, message_id, timeout_seconds,
        question=question, context=context, is_photo=is_photo,
        task_id=task_id, phase=phase, metadata=metadata, options=options or [],
    )


@mcp.tool()
async def send_telegram_photo(photo_path: str, caption: str = "") -> str:
    """
    Sends a one-way photo (e.g. a rendered diagram or e2e screenshot) to Telegram.

    Args:
        photo_path: Local path of the image (PNG/JPEG) to send.
        caption: Optional short caption (Markdown-special chars are escaped).

    Returns:
        Confirmation that the photo was sent, or an error message

    Examples:
        send_telegram_photo(
            "playwright-tests/latest_screenshots/web-admin/...-screenshot-admin-dashboard.png",
            caption="E2E run — admin dashboard",
        )
    """
    chat_id = await get_chat_id()
    if not chat_id:
        return "Error: Could not find a Telegram Chat ID."
    if not os.path.exists(photo_path):
        return f"Error: photo file not found: {photo_path}"

    user_part = _md_escape(caption) if caption else ""
    caption_text = f"🖼 **Kilo image:**\n\n{user_part}" if caption else "🖼 **Kilo image:**"
    payload = {
        "chat_id": chat_id,
        "caption": caption_text,
        "parse_mode": "Markdown",
    }
    try:
        with open(photo_path, "rb") as f:
            files = {"photo": (os.path.basename(photo_path), f, _mime_for(photo_path))}
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{TELEGRAM_API}/sendPhoto", data=payload, files=files)
        if resp.status_code != 200:
            return f"Error sending photo: {resp.text}"
        return f"✅ Photo sent to Telegram"
    except Exception as e:
        return f"Error sending photo: {e}"


@mcp.tool()
async def get_telegram_response(mark_as_read: bool = True) -> str:
    """
    Retrieves the most recent message from the user on Telegram.

    This tool is designed to work with ask_human(wait=False) for complex questions
    that require extended thinking time. After sending a question with wait=False,
    use this tool to retrieve the user's response when they're ready.

    Args:
        mark_as_read: If True (default), marks the message as processed so it won't
                     be retrieved again. Set to False if you want to re-read the message.

    Returns:
        The user's latest message text, or an error message if no new messages found.

    Examples:
        # After asking a complex question
        ask_human("Review this architecture and provide feedback", wait=False)
        # ... user thinks and replies on Telegram ...
        feedback = get_telegram_response()
    """
    chat_id = await get_chat_id()
    if not chat_id:
        return "Error: Could not find a Telegram Chat ID."

    # Get last processed update ID (0 if none processed yet)
    last_update_id = TelegramState.get_last_update_id()

    # Fetch new messages (if last_update_id is 0, this will fetch all messages)
    message = await get_latest_message(chat_id, since_update_id=last_update_id if last_update_id > 0 else None)

    if not message:
        return (
            "No new messages found on Telegram. "
            "Please reply to the question and try again."
        )

    # Re-read mode: return the text without consuming it or resolving the
    # pending question.
    if not mark_as_read:
        return message['text']

    # Update state if marking as read
    TelegramState.update_last_id(message['update_id'])

    # Mark the pending (wait=False) message resolved, mirroring poll_for_response
    pending = TelegramState.pending
    if pending:
        resolved = build_resolved_text(
            pending["question"], pending["context"], message['text'], "typed", _now_iso(),
            max_len=CAPTION_LIMIT if pending["is_photo"] else TEXT_LIMIT,
        )
        await _edit_message(pending["chat_id"], pending["message_id"], resolved, pending["is_photo"])
        _log_append(_log_snapshot(
            "resolved", pending["chat_id"], pending["message_id"], pending["question"],
            pending["options"], pending["task_id"], pending["phase"], pending["metadata"],
            decision=message['text'], via="typed",
        ))
        TelegramState.pending = None

    return message['text']


@mcp.tool()
async def get_telegram_history(task_id: str = "", limit: int = 20) -> str:
    """
    Returns the durable approval history from the JSONL audit log.

    Unlike list_telegram_messages (Telegram getUpdates, ~24h retention), the
    audit log persists every ask_human request and its resolution forever.

    Args:
        task_id: Optional filter. "" (default) = all records. A record whose
                 own task_id is empty matches ANY filter (legacy calls).
        limit: Max lines (default 20, max 100, values <=0 use the default).

    Returns:
        One line per message_id, newest first: timestamp, task/phase,
        decision (or Timed out / pending), and the question truncated to 80 chars.

    Examples:
        history = get_telegram_history(task_id="0077")
        history = get_telegram_history(limit=5)
    """
    limit = 20 if (not limit or limit <= 0) else min(limit, 100)
    records = []
    path = _log_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if not isinstance(rec, dict):
                        continue
                    records.append(rec)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

    if task_id:
        records = [r for r in records if not r.get("task_id") or r["task_id"] == task_id]

    # Dedupe by message_id: a terminal record (resolved/timeout) wins over pending
    def status_rank(status):
        return 0 if status == "pending" else 1

    by_message = {}
    for r in records:
        mid = r.get("message_id")
        cur = by_message.get(mid)
        if cur is None or status_rank(r.get("status")) > status_rank(cur.get("status")):
            by_message[mid] = r

    rows = sorted(by_message.values(), key=lambda r: str(r.get("ts", "")), reverse=True)[:limit]

    if not rows:
        return "No approval records found in the audit log."

    lines = []
    for r in rows:
        ts = str(r.get("ts", ""))
        hhmm = ts[11:16] if len(ts) >= 16 else ts
        ctx = _build_context(r.get("task_id", ""), r.get("phase", ""))
        q = r.get("question", "")
        q80 = q[:80] + ("…" if len(q) > 80 else "")
        label = ctx  # _build_context already renders "Task 0077 · Phase A"
        status = r.get("status")
        if status == "resolved":
            marker = f"✅ {r.get('decision', '?')} ({r.get('via', '?')})"
        elif status == "timeout":
            marker = "⏱️ Timed out"
        else:
            marker = "⏳ pending"
        lines.append(f"[{hhmm}] {label} → {marker} — \"{q80}\"")

    return f"# Approval history ({len(lines)} record(s))\n" + "\n".join(lines)


@mcp.tool()
async def send_telegram_notification(message: str) -> str:
    """
    Sends a one-way notification message to the user on Telegram.

    This tool is for sending status updates, progress reports, or completion
    notifications without expecting a response. Use this to keep the user
    informed during long-running tasks.

    Args:
        message: The notification text to send

    Returns:
        Confirmation that the message was sent, or an error message

    Examples:
        # Progress update
        send_telegram_notification("✅ Step 1/5 complete: Database schema created")

        # Task completion
        send_telegram_notification("🎉 Refactoring complete! Modified 23 files successfully.")

        # Status update
        send_telegram_notification("⏳ Running tests... this may take a few minutes")
    """
    chat_id = await get_chat_id()
    if not chat_id:
        return "Error: Could not find a Telegram Chat ID."

    payload = {
        "chat_id": chat_id,
        "text": f"📢 **Kilo Update:**\n\n{_md_escape(message)}",
        "parse_mode": "Markdown"
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
            if resp.status_code != 200:
                return f"Error sending notification: {resp.text}"

            return f"✅ Notification sent to Telegram"
        except Exception as e:
            return f"Error sending notification: {e}"


@mcp.tool()
async def list_telegram_messages(limit: int = 5) -> str:
    """
    Lists recent messages from your Telegram chat for context.

    Useful for reviewing conversation history or checking if you've already
    replied to a question. Also shows edited_message updates ([edited]) so
    resolved questions are visible, not their stale pre-edit text.

    Args:
        limit: Number of recent messages to retrieve (default 5, max 20).

    Returns:
        Formatted list of recent messages with timestamps.

    Example:
        messages = list_telegram_messages(limit=10)
    """
    chat_id = await get_chat_id()
    if not chat_id:
        return "Error: Could not find a Telegram Chat ID."

    limit = min(limit, 20)  # Cap at 20 messages

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{TELEGRAM_API}/getUpdates", params={"limit": 100})
            data = resp.json()

            if not data.get('result'):
                return "No messages found."

            # Filter chat-relevant updates FIRST, then slice — a resolved edit
            # adds an edited_message update that must not crowd out the chat's
            # own records (AC8).
            relevant = []
            for update in data['result']:
                if 'message' in update:
                    msg = update['message']
                    if str(msg['chat']['id']) == str(chat_id):
                        relevant.append((update, msg, "message"))
                elif 'edited_message' in update:
                    em = update['edited_message']
                    if str(em['chat']['id']) == str(chat_id):
                        relevant.append((update, em, "edited_message"))
                elif 'callback_query' in update:
                    cb = update['callback_query']
                    if str(cb['message']['chat']['id']) == str(chat_id):
                        relevant.append((update, cb, "callback_query"))

            relevant.sort(key=lambda t: t[0]['update_id'])
            messages = []
            for update, obj, kind in relevant[-limit:]:
                timestamp = obj.get('date', 0)
                if kind == "callback_query":
                    text = f"[Button: {obj['data']}]"
                    from_user = obj['from'].get('first_name', 'Unknown')
                else:
                    text = obj.get('text') or obj.get('caption') or '[No text]'
                    from_user = obj.get('from', {}).get('first_name', 'Unknown')
                    if kind == "edited_message":
                        text = f"[edited] {text}"
                messages.append(f"[{timestamp}] {from_user}: {text}")

            if not messages:
                return "No messages found in this chat."

            return "\n".join(messages[-limit:])  # Return only the requested limit

        except Exception as e:
            return f"Error fetching messages: {e}"


if __name__ == "__main__":
    mcp.run()
