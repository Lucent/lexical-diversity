#!/usr/bin/env bash
set -euo pipefail

REPO_NAME="$1"	# e.g. lucent.bsky.social
LIMIT="${2:-}"	# optional: number of latest posts to keep
ACCOUNT_DUMPS_DIR="./account_dumps"

goat repo export "$REPO_NAME"
LATEST_FILE="$(ls -1t "$REPO_NAME".*.car | head -n1)"
goat repo unpack "$LATEST_FILE"
DID_DIR="$(goat resolve "$REPO_NAME" | jq -r .id)"

if [ -n "$LIMIT" ]; then
  python3 bluesky-tools/thread_replies.py "$DID_DIR" "$LIMIT" > "$ACCOUNT_DUMPS_DIR/$REPO_NAME.txt"
else
  python3 bluesky-tools/thread_replies.py "$DID_DIR" > "$ACCOUNT_DUMPS_DIR/$REPO_NAME.txt"
fi

rm -r "$DID_DIR"
rm "$REPO_NAME".*.car
