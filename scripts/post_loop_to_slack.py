#!/usr/bin/env python3

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

SLACK_API_BASE = "https://slack.com/api"


def slack_api(method: str, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{SLACK_API_BASE}/{method}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as response:  # nosec B310 - HTTPS-only hardcoded URL
        return json.loads(response.read().decode("utf-8"))


def find_root_thread_ts(messages: List[Dict[str, Any]], marker: str) -> Optional[str]:
    for msg in messages:
        text = str(msg.get("text", ""))
        if marker in text:
            return str(msg.get("thread_ts") or msg.get("ts") or "") or None
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--token",
        default=None,
        help="Slack token (prefer SLACK_BOT_TOKEN env var)",
    )
    parser.add_argument("--channel", required=True)
    parser.add_argument("--message-path", required=True)
    parser.add_argument("--marker", default="[ultrawork-loop]")
    parser.add_argument("--history-limit", type=int, default=50)
    args = parser.parse_args()

    # Prefer env var over CLI arg to avoid token exposure in process list
    token = args.token or os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        print("No Slack token: set SLACK_BOT_TOKEN env var or pass --token")
        return 1

    message = Path(args.message_path).read_text(encoding="utf-8").strip()
    if not message:
        print("Loop message is empty, skipping Slack post.")
        return 0

    history = slack_api(
        "conversations.history",
        token,
        {"channel": args.channel, "limit": str(max(1, args.history_limit))},
    )
    if not history.get("ok"):
        print(f"conversations.history failed: {history}")
        return 1

    messages = history.get("messages", [])
    root_ts = find_root_thread_ts(messages, args.marker)

    payload: Dict[str, Any] = {
        "channel": args.channel,
        "text": message,
    }
    if root_ts:
        payload["thread_ts"] = root_ts

    posted = slack_api("chat.postMessage", token, payload)
    if not posted.get("ok"):
        print(f"chat.postMessage failed: {posted}")
        return 1

    print("Posted loop message to Slack thread" if root_ts else "Posted new loop root message to Slack")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
