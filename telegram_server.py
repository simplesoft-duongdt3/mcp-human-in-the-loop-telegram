import asyncio
import os
import httpx
from fastmcp import FastMCP
from dotenv import load_dotenv

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


class TelegramState:
    """Tracks state across tool calls to avoid re-processing messages"""
    last_processed_update_id: int = 0
    
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


async def send_telegram_message(chat_id: str, text: str, options: list[str] = None, allow_custom: bool = True) -> dict:
    """
    Sends a message to Telegram and returns the message info.
    
    Args:
        chat_id: Telegram chat ID to send to
        text: Message text to send
        options: Optional list of button options
        allow_custom: If True and options provided, adds "Custom answer" button
    
    Returns:
        dict with 'success', 'message_id', and optional 'error' keys
    """
    payload = {
        "chat_id": chat_id,
        "text": f"🤖 **Kilo has a question:**\n\n{text}",
        "parse_mode": "Markdown"
    }

    if options:
        # Create a grid of buttons (one per row)
        keyboard = []
        for opt in options:
            keyboard.append([{"text": opt, "callback_data": opt}])
        
        # Add "Custom answer" button if allowed
        if allow_custom:
            keyboard.append([{"text": "✏️ Custom answer (type below)", "callback_data": "__CUSTOM__"}])
        
        payload["reply_markup"] = {"inline_keyboard": keyboard}

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
            if resp.status_code != 200:
                return {"success": False, "error": resp.text}
            
            sent_message_id = resp.json()['result']['message_id']
            return {"success": True, "message_id": sent_message_id}
        except Exception as e:
            return {"success": False, "error": str(e)}


async def poll_for_response(chat_id: str, sent_message_id: int, timeout_seconds: int = 120) -> str:
    """
    Polls Telegram for a response to a specific message.
    
    Args:
        chat_id: Telegram chat ID to poll
        sent_message_id: ID of the message we're waiting for a response to
        timeout_seconds: Maximum time to wait
    
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
                        
                        # Edit the original message to show what was selected
                        await client.post(f"{TELEGRAM_API}/editMessageText", json={
                            "chat_id": chat_id,
                            "message_id": sent_message_id,
                            "text": f"✅ **Resolved**\n\nSelected: {answer}",
                            "parse_mode": "Markdown"
                        })
                        
                        # Update state
                        TelegramState.update_last_id(last_update_id)
                        return answer

                    # Check for Text Reply
                    if 'message' in update:
                        msg = update['message']
                        # Accept messages from the authorized user
                        if str(msg['chat']['id']) == str(chat_id):
                            user_text = msg.get('text', '')
                            # Update state
                            TelegramState.update_last_id(last_update_id)
                            return user_text

            except Exception as e:
                print(f"Polling error: {e}")
                await asyncio.sleep(1)

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
                            'text': msg.get('text', '[No text content]'),
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
    timeout_seconds: int = 120,
    allow_custom: bool = True
) -> str:
    """
    Sends a question to the user via Telegram.
    
    Args:
        question: The text of the question to ask the user.
        options: Optional list of short strings (e.g. ["Yes", "No"]) to show as buttons.
                 If provided and allow_custom=True, a "Custom answer" button is added.
        wait: If True (default), blocks until response received or timeout.
              If False, sends question and returns immediately.
        timeout_seconds: Maximum time to wait for response (only used if wait=True).
        allow_custom: If True (default) and options provided, adds a "Custom answer" button
                      allowing the user to type their own response instead of clicking a button.
    
    Returns:
        - If wait=True: The user's answer or timeout message
        - If wait=False: Confirmation message with instructions
    
    Examples:
        # Blocking mode with buttons and custom answer option
        answer = ask_human("Should I proceed?", options=["Yes", "No"])
        
        # Blocking mode with buttons only (no custom answer)
        answer = ask_human("Pick one:", options=["A", "B", "C"], allow_custom=False)
        
        # Non-blocking mode with buttons
        ask_human("Which approach?", options=["Option 1", "Option 2"], wait=False)
        # Later: answer = get_telegram_response()
    """
    chat_id = await get_chat_id()
    if not chat_id:
        return "Error: Could not find a Telegram Chat ID. Please message the bot first."
    
    # Send the message
    message_info = await send_telegram_message(chat_id, question, options, allow_custom)
    
    if not message_info['success']:
        return f"Error sending Telegram message: {message_info.get('error', 'Unknown error')}"
    
    # Non-blocking mode: return immediately
    if not wait:
        return (
            f"✅ Question sent to Telegram (Message ID: {message_info['message_id']}).\n\n"
            f"When you've replied, use the get_telegram_response() tool to retrieve your answer."
        )
    
    # Blocking mode: wait for response
    return await poll_for_response(chat_id, message_info['message_id'], timeout_seconds)


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
    
    # Update state if marking as read
    if mark_as_read:
        TelegramState.update_last_id(message['update_id'])
    
    return message['text']


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
        "text": f"📢 **Kilo Update:**\n\n{message}",
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
    replied to a question.
    
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
            
            messages = []
            for update in reversed(data['result'][-limit:]):
                if 'message' in update:
                    msg = update['message']
                    if str(msg['chat']['id']) == str(chat_id):
                        timestamp = msg.get('date', 0)
                        text = msg.get('text', '[No text]')
                        from_user = msg.get('from', {}).get('first_name', 'Unknown')
                        messages.append(f"[{timestamp}] {from_user}: {text}")
                
                if 'callback_query' in update:
                    cb = update['callback_query']
                    if str(cb['message']['chat']['id']) == str(chat_id):
                        timestamp = cb['message'].get('date', 0)
                        text = f"[Button: {cb['data']}]"
                        from_user = cb['from'].get('first_name', 'Unknown')
                        messages.append(f"[{timestamp}] {from_user}: {text}")
            
            if not messages:
                return "No messages found in this chat."
            
            return "\n".join(messages[-limit:])  # Return only the requested limit
            
        except Exception as e:
            return f"Error fetching messages: {e}"


if __name__ == "__main__":
    mcp.run()
