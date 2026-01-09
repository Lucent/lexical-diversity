#!/usr/bin/env bash
set -euo pipefail

REPO_NAME="$1"	# e.g. lucent.bsky.social
LIMIT="${2:-}"	# optional: number of latest posts to keep
ACCOUNT_DUMPS_DIR="./account_dumps"

echo "[fetch_repo.sh] Starting fetch for $REPO_NAME (limit: ${LIMIT:-all})"

echo "[fetch_repo.sh] Exporting repository..."
if ! goat repo export "$REPO_NAME" 2>&1; then
  echo "[fetch_repo.sh] ERROR: Username not found: $REPO_NAME" >&2
  exit 1
fi

LATEST_FILE="$(ls -1t "$REPO_NAME".*.car 2>/dev/null | head -n1)"
if [ -z "$LATEST_FILE" ]; then
  echo "[fetch_repo.sh] ERROR: Username not found: $REPO_NAME" >&2
  exit 1
fi
echo "[fetch_repo.sh] Unpacking $LATEST_FILE..."
goat repo unpack "$LATEST_FILE"

echo "[fetch_repo.sh] Resolving DID..."
DID_DIR="$(goat resolve "$REPO_NAME" 2>&1 | jq -r .id)"
if [ "$DID_DIR" = "null" ] || [ -z "$DID_DIR" ]; then
  echo "[fetch_repo.sh] ERROR: Username not found: $REPO_NAME" >&2
  exit 1
fi
echo "[fetch_repo.sh] DID: $DID_DIR"

echo "[fetch_repo.sh] Checking post count..."
POST_DIR="$DID_DIR/app.bsky.feed.post"
if [ ! -d "$POST_DIR" ]; then
  echo "[fetch_repo.sh] ERROR: No posts found for $REPO_NAME" >&2
  rm -r "$DID_DIR" 2>/dev/null || true
  rm "$REPO_NAME".*.car 2>/dev/null || true
  exit 1
fi

POST_COUNT=$(find "$POST_DIR" -type f -name "*.json" | wc -l)
echo "[fetch_repo.sh] Found $POST_COUNT posts"

if [ "$POST_COUNT" -lt 50 ]; then
  echo "[fetch_repo.sh] ERROR: Insufficient data: $REPO_NAME has only $POST_COUNT posts (minimum 50 required)" >&2
  rm -r "$DID_DIR" 2>/dev/null || true
  rm "$REPO_NAME".*.car 2>/dev/null || true
  exit 1
fi

echo "[fetch_repo.sh] Extracting posts..."
if [ -n "$LIMIT" ]; then
  python3 bluesky-tools/thread_replies.py "$DID_DIR" "$LIMIT" > "$ACCOUNT_DUMPS_DIR/$REPO_NAME.txt"
else
  python3 bluesky-tools/thread_replies.py "$DID_DIR" > "$ACCOUNT_DUMPS_DIR/$REPO_NAME.txt"
fi

echo "[fetch_repo.sh] Cleaning up..."
rm -r "$DID_DIR"
rm "$REPO_NAME".*.car

echo "[fetch_repo.sh] Complete! Output saved to $ACCOUNT_DUMPS_DIR/$REPO_NAME.txt"
