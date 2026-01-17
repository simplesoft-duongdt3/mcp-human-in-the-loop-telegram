#!/bin/bash
# Startup script for Telegram MCP Server
# This script activates the virtual environment and runs the server

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate virtual environment
source "$SCRIPT_DIR/venv/bin/activate"

# Run the server
python "$SCRIPT_DIR/telegram_server.py"
