#!/bin/bash
cd "$(dirname "$0")"

# Set library path for Cairo (required for PNG rendering)
export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH

uvicorn backend.main:app --reload --port 8000
