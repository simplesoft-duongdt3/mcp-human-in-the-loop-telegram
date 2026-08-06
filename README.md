# Telegram MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-supported-blue.svg)](https://www.docker.com/)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![Telegram Bot API](https://img.shields.io/badge/Telegram-Bot%20API-blue.svg)](https://core.telegram.org/bots/api)

A Model Context Protocol (MCP) server that enables AI assistants (like Kilo Code) to ask you questions via Telegram and wait for your responses. This creates a "human-in-the-loop" workflow where the AI can request decisions, approvals, or specific input during long-running tasks.

## Features

- 🤖 **Interactive AI Workflow**: AI can pause and ask you questions via Telegram
- 📱 **Button Support**: Present multiple choice options as clickable buttons
- ⏱️ **Long Polling**: Waits up to 2 minutes for your response
- 🔒 **Secure**: Uses environment variables for credentials
- 🎯 **Simple Integration**: Works with any MCP-compatible AI assistant
- 🐳 **Docker Support**: Run natively or in a container

## Prerequisites

- Python 3.10+ (for native installation)
- OR Docker and Docker Compose (for containerized installation)
- A Telegram account
- A Telegram Bot Token (from @BotFather)

## Installation Methods

You can run this MCP server in two ways:

1. **[Native Python Installation](#native-installation)** - Run directly on your system
2. **[Docker Installation](#docker-installation)** - Run in a container (recommended for production)

## Native Installation

### 1. Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Name your bot (e.g., "MyDevBot")
4. Copy the **HTTP API Token** provided
5. **Important**: Send `/start` to your new bot so it can message you

### 2. Find Your Telegram User ID (Optional)

1. Search for **@userinfobot** on Telegram
2. Send it any message
3. Copy your User ID

### 3. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/telegram-mcp-server.git
cd telegram-mcp-server

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Linux/Mac
# OR
venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r requirements.txt
```

### 4. Configuration

Create a `.env` file from the sample:

```bash
cp .env.sample .env
```

Edit `.env` and add your credentials:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_USER_ID=your_user_id_here  # Optional - bot will auto-detect if not set
```

⚠️ **Security Note**: The `.env` file is gitignored to protect your credentials.

### 5. Test the Server Locally

```bash
# Activate virtual environment
source venv/bin/activate

# Run the server
python telegram_server.py
```

You should see:
```
╭──────────────────────────────────────────────────────────────────────────────╮
│                         ▄▀▀ ▄▀█ █▀▀ ▀█▀ █▀▄▀█ █▀▀ █▀█                        │
│                         █▀  █▀█ ▄▄█  █  █ ▀ █ █▄▄ █▀▀                        │
│                                FastMCP 2.14.2                                │
│                    🖥  Server:      Telegram Human Loop                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Press `Ctrl+C` to stop the test.

## Docker Installation

### 1. Configure Environment

```bash
cp .env.sample .env
# Edit .env with your credentials
```

### 2. Build and Run

```bash
# Build the Docker image
docker-compose build

# Start the container in detached mode
docker-compose up -d
```

### 3. View Logs

```bash
docker-compose logs -f telegram-mcp
```

### 4. Stop the Server

```bash
docker-compose down
```

### Docker Commands Reference

**Building:**
```bash
# Build the image
docker-compose build

# Build without cache (force rebuild)
docker-compose build --no-cache
```

**Running:**
```bash
# Start in detached mode (background)
docker-compose up -d

# Start in foreground (see logs directly)
docker-compose up

# Start and rebuild if needed
docker-compose up -d --build
```

**Monitoring:**
```bash
# View logs
docker-compose logs -f telegram-mcp

# View last 100 lines of logs
docker-compose logs --tail=100 telegram-mcp

# Check container status
docker-compose ps

# Execute commands inside the container
docker-compose exec telegram-mcp python --version
```

**Stopping and Cleaning:**
```bash
# Stop the container
docker-compose stop

# Stop and remove containers
docker-compose down

# Stop, remove containers, and remove volumes
docker-compose down -v

# Remove all (containers, networks, images)
docker-compose down --rmi all
```

**Restart:**
```bash
# Restart the container
docker-compose restart

# Rebuild and restart from scratch
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

**Development:**
```bash
# Open a shell in the running container
docker-compose exec telegram-mcp /bin/bash

# Test the server locally (without Docker)
source venv/bin/activate && python telegram_server.py
```

## Connecting to MCP Clients

### For Kilo Code (or similar MCP clients)

#### Method 1: Using the Startup Script (Recommended)

1. Open your MCP settings file:
   - Location: `~/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcpSettings.json`
   - Or use your client's UI: Settings → MCP Servers → Edit Configuration

2. Add this configuration (**replace `/absolute/path/to/telegram-mcp-server` with your actual installation path**):

```json
{
  "mcpServers": {
    "telegram": {
      "command": "bash",
      "args": ["/absolute/path/to/telegram-mcp-server/run.sh"]
    }
  }
}
```

**Example:** If you cloned to `/home/user/projects/telegram-mcp-server`, use:
```json
{
  "mcpServers": {
    "telegram": {
      "command": "bash",
      "args": ["/home/user/projects/telegram-mcp-server/run.sh"]
    }
  }
}
```

3. Restart your MCP client or reload the MCP servers

**Note:** An example configuration is provided in `mcp-config.example.json` for reference.

#### Method 2: Direct Python Execution

```json
{
  "mcpServers": {
    "telegram": {
      "command": "/absolute/path/to/telegram-mcp-server/venv/bin/python",
      "args": ["/absolute/path/to/telegram-mcp-server/telegram_server.py"]
    }
  }
}
```

#### Method 3: Using Docker

**Option A: Docker Compose Exec**

```json
{
  "mcpServers": {
    "telegram": {
      "command": "docker-compose",
      "args": [
        "-f",
        "/absolute/path/to/telegram-mcp-server/docker-compose.yml",
        "exec",
        "-T",
        "telegram-mcp",
        "python",
        "telegram_server.py"
      ],
      "cwd": "/absolute/path/to/telegram-mcp-server"
    }
  }
}
```

**Option B: Docker Run**

```json
{
  "mcpServers": {
    "telegram": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--env-file",
        "/absolute/path/to/telegram-mcp-server/.env",
        "telegram-mcp-server",
        "python",
        "telegram_server.py"
      ]
    }
  }
}
```

## Available Tools

Once connected, your AI assistant will have access to these tools:

1. **ask_human(question, options, wait, timeout_seconds, allow_custom)** - Send questions to Telegram
   - `wait=True` (default): Blocks until you respond or timeout
   - `wait=False`: Sends question and returns immediately (non-blocking mode)
   - `options`: Optional list of button choices
   - `allow_custom=True` (default): Adds "Custom answer" button when options provided
   - Works in both blocking and non-blocking modes

2. **get_telegram_response(mark_as_read)** - Retrieve your latest Telegram message
   - Use after `ask_human(wait=False)` to get your response
   - `mark_as_read=True` (default): Won't retrieve the same message twice

3. **send_telegram_notification(message)** - Send one-way status updates
   - For progress reports, completion notifications, or status updates
   - Doesn't expect a response
   - Perfect for keeping you informed during long-running tasks

4. **list_telegram_messages(limit)** - View recent conversation history
   - Shows last 5-20 messages for context
   - Useful for checking if you've already replied

## Usage Examples

### Example 1: Simple Question

**You say to your AI:**
> "I'm going to grab coffee. If you need to know which database to use, ask me via Telegram."

**AI calls:**
```python
ask_human(question="Should I use PostgreSQL or MongoDB for this project?")
```

**What happens:**
1. Your phone buzzes with a Telegram message
2. You reply: "PostgreSQL"
3. AI receives "PostgreSQL" and continues

### Example 2: Multiple Choice with Buttons

**AI calls:**
```python
ask_human(
    question="How should I structure the authentication?",
    options=["JWT", "Session Cookies", "OAuth2", "Skip for now"]
)
```

**What happens:**
1. You receive a Telegram message with 4 clickable buttons
2. You tap "JWT"
3. AI receives "JWT" instantly

### Example 3: Approval Workflow

**You say to your AI:**
> "Refactor the entire codebase, but ask me before making any breaking changes."

**AI calls:**
```python
ask_human(
    question="I want to rename `getUserData()` to `fetchUser()`. This will break 23 files. Proceed?",
    options=["Yes, proceed", "No, skip this", "Show me the files first"]
)
```

### Example 4: Non-Blocking Mode for Complex Questions

**AI asks without waiting:**
```python
ask_human(
    question="Please review this 500-line refactor and provide detailed feedback",
    wait=False
)
```

**What happens:**
1. You receive the question on Telegram
2. You take your time to review (no timeout)
3. When ready, you tell the AI: "I've answered on Telegram"
4. AI retrieves your answer: `get_telegram_response()`

### Example 5: Progress Notifications

**AI sends status updates:**
```python
send_telegram_notification("🚀 Starting database migration...")
send_telegram_notification("✅ Step 1/5 complete: Schema created")
send_telegram_notification("🎉 Migration complete! All 1,247 records migrated successfully.")
```

## How It Works

1. **AI calls `ask_human()`** with a question and optional button choices
2. **Server sends Telegram message** to your configured chat
3. **Long polling loop** checks Telegram every 2 seconds for your response
4. **You respond** via text or button click
5. **Server returns your answer** to the AI
6. **AI continues** with your input

### Timeout Behavior

- Default timeout: **180 seconds** (3 minutes) — the Kilo MCP client timeout must be ≥ this (see the task-0077 section below)
- Configurable via the `timeout_seconds` parameter in `ask_human()`
- If you don't respond in time, the AI receives: `"Timeout: User did not respond in time..."`

### Non-Blocking Mode

For complex questions that require extended thinking time, use **non-blocking mode** to avoid timeouts:

1. **AI asks without waiting:**
   ```python
   ask_human("Please review this architecture and provide feedback", wait=False)
   ```

2. **You receive the question** and can take as long as needed to think and respond

3. **When ready, tell the AI you've replied:**
   > "I've answered on Telegram"

4. **AI retrieves your answer:**
   ```python
   answer = get_telegram_response()
   ```

### Custom Answers with Buttons

When you provide button options, the AI automatically adds a "✏️ Custom answer" button (unless `allow_custom=False`). This lets you:
- Click a button for quick selection
- OR type your own custom response

**Example:**
```python
ask_human(
    "Which database?",
    options=["PostgreSQL", "MongoDB", "MySQL"],
    wait=False
)
```

You'll see 4 buttons:
- PostgreSQL
- MongoDB
- MySQL
- ✏️ Custom answer (type below)

## Best Practices

**Use Non-Blocking Mode (`wait=False`) when:**
- Questions require code review or deep analysis
- You might be away from your device
- The decision requires research or consultation
- You need more than 2 minutes to respond

**Use Blocking Mode (`wait=True`) when:**
- Questions are simple yes/no decisions
- You're actively working with the AI
- Quick responses are expected
- Using button options for multiple choice

**Use Notifications (`send_telegram_notification`) for:**
- Progress updates during long-running tasks
- Task completion notifications
- Error or warning alerts
- Status updates that don't require a response
- Keeping yourself informed while away from the computer

## Project Structure

```
telegram-mcp-server/
├── telegram_server.py         # Main MCP server code
├── .env                       # Your credentials (gitignored)
├── .env.sample               # Template for environment variables
├── .gitignore                # Protects secrets
├── requirements.txt          # Python dependencies
├── run.sh                    # Startup script (executable)
├── mcp-config.example.json   # Example MCP configuration (customize for your setup)
├── Dockerfile                # Docker image definition
├── docker-compose.yml        # Docker Compose configuration
├── .dockerignore             # Docker build exclusions
└── README.md                 # This file
```

## Troubleshooting

### "Command 'python' not found"

**Solution**: Use `python3` instead, or install the symlink:
```bash
sudo apt install python-is-python3
```

The `run.sh` script already uses the correct Python from the virtual environment.

### "Error: Could not find a Telegram Chat ID"

**Solution**: Make sure you've sent `/start` to your bot at least once.

### "Permission denied: ./run.sh"

**Solution**: Make the script executable:
```bash
chmod +x run.sh
```

### "Timeout: User did not respond in time"

**Solutions**:
- Respond faster (within 2 minutes)
- Increase timeout in the `ask_human()` call
- Use non-blocking mode (`wait=False`) for complex questions

### MCP Server Not Showing in Client

**Solutions**:
1. Check the MCP settings file path is correct
2. Verify the absolute path in your configuration
3. Restart your MCP client completely
4. Check client logs for connection errors

### Docker Container Won't Start

Check logs:
```bash
docker-compose logs telegram-mcp
```

### Environment Variables Not Loading

Ensure `.env` file exists and is properly formatted:
```bash
cat .env
```

### Permission Issues with Docker

If you encounter permission issues, ensure the `.env` file is readable:
```bash
chmod 644 .env
```

## Advanced Configuration

### Changing the Default Timeout

You can customize the timeout per question:

```python
# Short timeout for quick questions
ask_human("Proceed?", options=["Yes", "No"], timeout_seconds=30)

# Longer timeout for thoughtful questions
ask_human("Which approach?", timeout_seconds=180)  # 3 minutes (max for blocking; use wait=False beyond that)
```

### Restricting to Specific User

The server uses `TELEGRAM_USER_ID` from `.env`. Only messages from this user ID will be accepted.

### Using Multiple Bots

Create separate directories with different `.env` files and register each as a different MCP server:

```json
{
  "mcpServers": {
    "telegram-work": {
      "command": "bash",
      "args": ["/path/to/work-bot/run.sh"]
    },
    "telegram-personal": {
      "command": "bash",
      "args": ["/path/to/personal-bot/run.sh"]
    }
  }
}
```

## Security Best Practices

1. ✅ **Never commit `.env`** - Already in `.gitignore`
2. ✅ **Use `TELEGRAM_USER_ID`** - Prevents unauthorized users from controlling your AI
3. ✅ **Regenerate tokens** if accidentally exposed
4. ✅ **Use private Telegram bots** - Don't share your bot with others
5. ✅ **Use Docker secrets** for sensitive data in production
6. ✅ **Regularly update** the base Python image for security patches

## Production Deployment

For production deployment:

1. Remove development volume mounts from `docker-compose.yml`
2. Use environment variables or secrets management instead of `.env` file
3. Consider using a process manager or orchestration tool (Kubernetes, Docker Swarm)
4. Set up proper logging and monitoring
5. Configure restart policies appropriately

Example production docker-compose.yml:

```yaml
version: '3.8'

services:
  telegram-mcp:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: telegram-mcp-server
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_USER_ID=${TELEGRAM_USER_ID}
      - PYTHONUNBUFFERED=1
    restart: always
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

## Dependencies

- **fastmcp** (2.14.2+) - MCP server framework
- **httpx** (0.28.1+) - Async HTTP client for Telegram API
- **python-dotenv** (1.2.1+) - Environment variable management

See `requirements.txt` for full list.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - Use freely!

## Support

For issues with:
- **MCP Protocol**: Check [Model Context Protocol docs](https://modelcontextprotocol.io/)
- **FastMCP**: Visit [FastMCP documentation](https://gofastmcp.com)
- **Telegram Bot API**: See [Telegram Bot API docs](https://core.telegram.org/bots/api)

## Changelog

### v1.0.0 (2026-01-02)
- Initial release
- Support for blocking and non-blocking question modes
- Button support for multiple choice questions
- Progress notification system
- Docker support
- Comprehensive documentation

## Approval history & diagram images (task 0077)

- **History:** every `ask_human` request and its resolution (button click,
  typed text, or timeout) is appended to a durable JSONL audit log — default
  `~/.config/kilo/telegram-hitl.log.jsonl`, overridable with the
  `TELEGRAM_HITL_LOG_PATH` env var. Query it with the `get_telegram_history`
  MCP tool (filter by `task_id`, one line per message, newest first). Unlike
  Telegram's `getUpdates` (≈24h retention) the log persists forever.
- **Resolved messages keep context:** the original question, task/phase,
  decision and timestamp stay visible after resolution (buttons are removed);
  typed replies and timeouts are marked resolved too.
- **Diagrams/photos:** pass `photo_path` to `ask_human` to attach an image
  (e.g. a rendered mermaid diagram — render with
  `bash scripts/render-mermaid.sh <md> <outdir>` in the project repo). The
  question becomes a photo message; resolutions edit the caption. Use
  `send_telegram_photo(photo_path, caption)` for one-way images (e.g. e2e
  screenshots). Photo messages have a 1024-char caption limit.
- **Context params:** `ask_human(..., task_id="0077", phase="A",
  metadata={...})` — `task_id`/`phase` appear in the message header and are
  recorded in the log; `metadata` is log-only, never sent to Telegram.
- **Timeouts:** default `timeout_seconds=180` (3 minutes) — the Kilo MCP
  client timeout must be ≥ that value (`.kilo/kilo.jsonc` → `timeout: 180000`).
  For longer deliberations use `wait=False` + `get_telegram_response()`.
- **Markdown safety:** questions, decisions and captions are escaped before
  sending/editing (`_ * ` [ ]`); on a Telegram parse error the edit is retried
  without `parse_mode`. Keep question text free of unpaired specials.
