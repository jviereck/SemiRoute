#!/bin/bash
cd "$(dirname "$0")"

# Set library path for Cairo (required for PNG rendering)
export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH

# Determine port based on git branch
# main -> 8000, *-a -> 8001, *-b -> 8002, etc.
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
PORT=8000

if [[ "$BRANCH" == "main" ]]; then
    PORT=8000
elif [[ "$BRANCH" =~ -([a-z])$ ]]; then
    SUFFIX="${BASH_REMATCH[1]}"
    # Convert letter to offset: a=1, b=2, etc.
    OFFSET=$(printf '%d' "'$SUFFIX")
    OFFSET=$((OFFSET - 96))  # 'a' is ASCII 97, so 97-96=1
    PORT=$((8000 + OFFSET))
fi

echo "Starting server on port $PORT (branch: $BRANCH)"
uvicorn backend.main:app --reload --port "$PORT"
