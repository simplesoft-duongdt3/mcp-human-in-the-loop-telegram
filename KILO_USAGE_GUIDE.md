# Kilo Code: Telegram Integration Usage Guide

This guide helps Kilo Code intelligently use the Telegram MCP server tools to interact with the user.

## Available Tools

### 1. `ask_human(question, options, wait, timeout_seconds)`

Sends a question to the user via Telegram.

**Parameters:**
- `question` (required): The question text
- `options` (optional): List of button choices (e.g., `["Yes", "No"]`)
- `wait` (optional, default `True`): Whether to block waiting for response
- `timeout_seconds` (optional, default `180`): How long to wait if `wait=True` (3 minutes — matches the MCP client timeout; use `wait=False` + `get_telegram_response()` beyond that)

**Returns:**
- If `wait=True`: The user's answer or timeout message
- If `wait=False`: Confirmation that question was sent

### 2. `get_telegram_response(mark_as_read)`

Retrieves the user's latest Telegram message.

**Parameters:**
- `mark_as_read` (optional, default `True`): Whether to mark message as processed

**Returns:**
- The user's message text, or error if no new messages

### 3. `list_telegram_messages(limit)`

Shows recent conversation history.

**Parameters:**
- `limit` (optional, default `5`, max `20`): Number of messages to retrieve

**Returns:**
- Formatted list of recent messages with timestamps

## Decision Framework: When to Use Each Mode

### Use Non-Blocking Mode (`wait=False`)

**Complex Questions Requiring Deep Thought:**
- Code review requests
- Architecture decisions
- Comparing multiple implementation approaches
- Questions requiring research or documentation review
- Strategic decisions about project direction

**User Availability Concerns:**
- User mentioned they're stepping away
- User is in a meeting or busy
- Late night/early morning questions
- User explicitly requested non-blocking mode

**Examples:**
```python
# Code review
ask_human(
    "I've refactored the authentication system. Please review the changes "
    "in auth.js and let me know if the approach looks good.",
    wait=False
)

# Architecture decision
ask_human(
    "I've identified 3 database schema designs. Please review the diagrams "
    "in /docs/schemas/ and tell me which one best fits our needs.",
    wait=False
)

# Complex comparison
ask_human(
    "Should we use:\n"
    "1. Microservices with Docker\n"
    "2. Monolith with modular architecture\n"
    "3. Serverless with AWS Lambda\n\n"
    "Please consider our team size, budget, and scaling needs.",
    wait=False
)
```

### Use Blocking Mode (`wait=True`)

**Simple, Quick Decisions:**
- Yes/No questions
- Simple confirmations
- Quick preferences
- Multiple choice with clear options

**Active Collaboration:**
- User is actively working with you
- Rapid back-and-forth conversation
- Time-sensitive decisions
- User expects immediate interaction

**Examples:**
```python
# Simple confirmation
ask_human(
    "Should I create a backup before proceeding?",
    options=["Yes", "No"],
    wait=True
)

# Quick preference
ask_human(
    "Use TypeScript or JavaScript for this component?",
    options=["TypeScript", "JavaScript"],
    wait=True,
    timeout_seconds=60  # Shorter timeout for simple question
)

# Immediate decision
ask_human(
    "I'm about to modify 15 files. Create a git branch first?",
    options=["Yes, create branch", "No, work on main"],
    wait=True
)
```

## Workflow Patterns

### Pattern 1: Non-Blocking with Continuation

```python
# Ask complex question
ask_human(
    "Please review the refactoring plan in REFACTOR.md and let me know "
    "which approach you prefer.",
    wait=False
)

# Tell user you're waiting
# "I've sent a question to your Telegram about the refactoring approach. "
# "Let me know when you've replied, or I can continue with other tasks."

# When user says they've replied:
response = get_telegram_response()

# Continue based on response
if "approach 1" in response.lower():
    # Implement approach 1
    pass
```

### Pattern 2: Blocking with Timeout Handling

```python
answer = ask_human(
    "Should I proceed with this change?",
    options=["Yes", "No", "Let me review first"],
    wait=True,
    timeout_seconds=180
)

if "timeout" in answer.lower():
    # Handle timeout gracefully
    # "I didn't receive a response in time. I'll wait for your guidance "
    # "before proceeding with this change."
else:
    # Process the answer
    pass
```

### Pattern 3: Check History Before Asking

```python
# Check if user already answered
history = list_telegram_messages(limit=10)

if "already answered" in history:
    # User might have already replied
    response = get_telegram_response(mark_as_read=False)
else:
    # Ask the question
    ask_human("What's your preference?", wait=False)
```

### Pattern 4: Progressive Timeout

```python
# Start with short timeout
answer = ask_human(
    "Quick question: Should I use async/await here?",
    options=["Yes", "No"],
    wait=True,
    timeout_seconds=30
)

if "timeout" in answer.lower():
    # User might be busy, switch to non-blocking
    ask_human(
        "I see you're busy. I've sent a question to Telegram. "
        "Reply when you have a moment.",
        wait=False
    )
```

## Best Practices

### 1. Provide Context in Questions

**Bad:**
```python
ask_human("Which one?", options=["A", "B", "C"])
```

**Good:**
```python
ask_human(
    "I found 3 ways to implement caching:\n\n"
    "A. Redis (fast, requires separate service)\n"
    "B. In-memory (simple, loses data on restart)\n"
    "C. File-based (persistent, slower)\n\n"
    "Which approach fits our needs best?",
    options=["A - Redis", "B - In-memory", "C - File-based"]
)
```

### 2. Set Appropriate Timeouts

```python
# Quick questions: 30-60 seconds
ask_human("Proceed?", timeout_seconds=30)

# Normal questions: 180 seconds (default)
ask_human("Which approach?")

# Thoughtful questions: non-blocking (blocking is capped at 180 s by the MCP client timeout)
ask_human("Review this architecture", wait=False)
# Later: feedback = get_telegram_response()
# OR
ask_human("Review this architecture", wait=False)
```

### 3. Handle Timeouts Gracefully

```python
answer = ask_human("Should I refactor this?", wait=True)

if "timeout" in answer.lower():
    # Don't just fail - provide options
    # "I didn't hear back in time. I'll proceed with the safer option "
    # "(no refactoring) for now. Let me know if you'd like me to revisit this."
```

### 4. Use Buttons for Clear Choices

```python
# Good use of buttons
ask_human(
    "How should I handle errors?",
    options=["Throw exception", "Return null", "Log and continue"]
)

# Don't use buttons for open-ended questions
ask_human(
    "What are your thoughts on this implementation?",
    # No options - expecting detailed text response
)
```

### 5. Communicate Your State

When using non-blocking mode, tell the user what you're doing:

```python
ask_human("Complex question here...", wait=False)

# Then tell the user:
# "I've sent a question to your Telegram. While you're thinking about it, "
# "I'll continue with the unit tests. Let me know when you've replied."
```

### 6. Verify Before Proceeding

For critical operations, always ask:

```python
ask_human(
    "⚠️ WARNING: This will delete 50 files. Are you sure?",
    options=["Yes, I'm sure", "No, cancel"],
    wait=True
)
```

## Error Handling

### No New Messages

```python
response = get_telegram_response()

if "No new messages" in response:
    # User hasn't replied yet
    # "I don't see a response yet. Take your time - use get_telegram_response() "
    # "again when you're ready, or let me know if you'd like me to proceed "
    # "with a default option."
```

### Chat ID Not Found

```python
answer = ask_human("Question?")

if "Could not find a Telegram Chat ID" in answer:
    # User needs to message the bot first
    # "It looks like you haven't messaged the Telegram bot yet. "
    # "Please send /start to the bot, then I can ask you questions there."
```

## Examples by Use Case

### Code Review

```python
ask_human(
    "I've refactored the database layer in the following files:\n"
    "- models/user.js\n"
    "- models/post.js\n"
    "- db/connection.js\n\n"
    "Please review the changes and let me know if the approach looks good.",
    wait=False
)
```

### Architecture Decision

```python
ask_human(
    "For the new API, should we use:\n\n"
    "1. REST with Express.js (familiar, well-documented)\n"
    "2. GraphQL with Apollo (flexible, modern)\n"
    "3. gRPC (fast, type-safe)\n\n"
    "Consider our team's experience and project requirements.",
    wait=False
)
```

### Quick Confirmation

```python
ask_human(
    "I'm about to install 5 new npm packages. Proceed?",
    options=["Yes", "No", "Show me the packages first"],
    wait=True,
    timeout_seconds=60
)
```

### Breaking Change Warning

```python
ask_human(
    "⚠️ This refactoring will rename getUserData() to fetchUser() "
    "across 23 files. This is a breaking change. Proceed?",
    options=["Yes, proceed", "No, skip this", "Show me the affected files"],
    wait=True
)
```

### Preference Question

```python
ask_human(
    "For error handling, would you prefer:\n"
    "A. Try-catch blocks (explicit)\n"
    "B. Error boundaries (React-style)\n"
    "C. Result types (functional)",
    options=["A", "B", "C"],
    wait=True
)
```

## Summary

- **Use `wait=False`** for complex questions requiring thought
- **Use `wait=True`** for quick decisions and active collaboration
- **Provide context** in your questions
- **Handle timeouts gracefully** with fallback options
- **Communicate your state** when waiting for responses
- **Use buttons** for clear multiple-choice questions
- **Set appropriate timeouts** based on question complexity

Remember: The goal is to create a smooth, non-frustrating experience for the user while getting the information you need to complete tasks effectively.

## Task-workflow usage (approval history + diagram images)

The repo workflow (`docs/workflows/workflow-task.md`) gates each task phase
through Telegram. Use the context params so the history stays meaningful:

```python
# Phase A spec approval, with the rendered diagram attached
answer = ask_human(
    "Approve the spec for task 0077?",
    options=["Approve", "Reject"],
    task_id="0077",
    phase="A",
    photo_path="docs/tasks/0077-.../diagrams/01-01_detail-diagram-01.png",
)
```

- Render task diagrams first:
  `bash scripts/render-mermaid.sh docs/tasks/NNNN-slug/01_detail.md docs/tasks/NNNN-slug/diagrams`
- After the human answers, the original Telegram message is edited to a
  self-contained "resolved" text (question + task/phase + decision +
  timestamp) — scrolling history always tells you what was approved.
- Audit trail: `get_telegram_history(task_id="0077")` lists every approval
  for the task from the durable JSONL log, even after Telegram's ~24h
  update window.
- Send e2e screenshots at the end-task gate:
  `send_telegram_photo("playwright-tests/latest_screenshots/web/....png", caption="E2E reader")`
- Keep question text free of unpaired `_`, `*` and backticks (Telegram
  Markdown), or they will be escaped literally.
