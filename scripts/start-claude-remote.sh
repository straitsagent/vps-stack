#!/usr/bin/env bash
SESSION="claude-remote"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Session '$SESSION' already exists — attaching."
    tmux attach -t "$SESSION"
else
    echo "Creating new session '$SESSION'."
    tmux new-session -s "$SESSION"
fi
