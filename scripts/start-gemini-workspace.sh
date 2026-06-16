#!/usr/bin/env bash
SESSION="gemini-workspace"

# Function to attach to the session or switch to it if already inside tmux
attach_or_switch() {
    if [ -n "$TMUX" ]; then
        tmux switch-client -t "$SESSION"
    else
        tmux attach -t "$SESSION"
    fi
}

# Check if session exists
if tmux has-session -t "$SESSION" 2>/dev/null; then
    attach_or_switch
    exit 0
fi

# Create a new minimalist session with a single window
tmux new-session -d -s "$SESSION" -n "gemini"

# Attach/Switch
attach_or_switch
