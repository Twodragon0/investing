#!/usr/bin/env python3

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from glob import glob
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "_posts"
SLACK_API_BASE = "https://slack.com/api"


def env_first(*keys: str) -> str:
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def slack_api(method: str, token: str, data: Dict[str, Any]) -> Dict[str, Any]:
    payload = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        f"{SLACK_API_BASE}/{method}",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode("utf-8"))


def read_frontmatter_value(file_path: Path, key: str) -> str:
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    marker = f"{key}:"
    for line in text.splitlines():
        if line.startswith(marker):
            value = line[len(marker) :].strip().strip('"')
            return value
    return ""


def latest_post(pattern: str) -> Optional[Path]:
    matches = sorted(glob(str(POSTS_DIR / pattern)))
    if not matches:
        return None
    return Path(matches[-1])


def build_summary_text() -> str:
    daily_summary = latest_post("*daily-news-summary*.md")
    market_report = latest_post("*daily-market-report*.md")

    if not daily_summary and not market_report:
        return "오늘 투자 요약 데이터를 찾지 못했습니다."

    lines: List[str] = ["오늘 투자 소식 요약입니다."]

    if daily_summary:
        title = read_frontmatter_value(daily_summary, "title") or "일일 뉴스 요약"
        excerpt = read_frontmatter_value(daily_summary, "excerpt")
        slug = daily_summary.stem
        parts = slug.split("-", 3)
        if len(parts) == 4:
            link = f"https://investing.2twodragon.com/market-analysis/{parts[0]}/{parts[1]}/{parts[2]}/{parts[3]}/"
        else:
            link = "https://investing.2twodragon.com/"
        lines.append(f"- 요약: {title}")
        if excerpt:
            lines.append(f"- 핵심: {excerpt[:180]}")
        lines.append(f"- 링크: {link}")

    if market_report:
        title = read_frontmatter_value(market_report, "title") or "일일 시장 리포트"
        slug = market_report.stem
        parts = slug.split("-", 3)
        if len(parts) == 4:
            link = f"https://investing.2twodragon.com/market-analysis/{parts[0]}/{parts[1]}/{parts[2]}/{parts[3]}/"
        else:
            link = "https://investing.2twodragon.com/"
        lines.append(f"- 시장: {title}")
        lines.append(f"- 링크: {link}")

    return "\n".join(lines)


def has_bot_reply(
    token: str, channel_id: str, thread_ts: str, bot_user_id: str
) -> bool:
    replies = slack_api(
        "conversations.replies",
        token,
        {
            "channel": channel_id,
            "ts": thread_ts,
            "inclusive": "true",
            "limit": 50,
        },
    )
    if not replies.get("ok"):
        return False
    for message in replies.get("messages", []):
        if message.get("user") == bot_user_id and message.get("ts") != thread_ts:
            return True
    return False


def should_reply(text: str, bot_user_id: str) -> bool:
    lowered = text.lower()
    mention_token = f"<@{bot_user_id}>".lower()
    has_mention = mention_token in lowered or "openclaw" in lowered
    has_intent = any(
        key in lowered
        for key in ["투자", "요약", "소식", "summary", "market", "news", "브리핑"]
    )
    return has_mention and has_intent


def main() -> int:
    token = env_first("SLACK_BOT_TOKEN", "OPENCLAW_SLACK_BOT_TOKEN", "SLACK_TOKEN")
    channel_id = env_first(
        "SLACK_CHANNEL_ID", "OPENCLAW_SLACK_CHANNEL_ID", "SLACK_CHANNEL"
    )

    if not token or not channel_id:
        print("Missing Slack token or channel. Skipping mention responder.")
        return 0

    auth = slack_api("auth.test", token, {})
    if not auth.get("ok"):
        print(f"auth.test failed: {auth}")
        return 1

    bot_user_id = auth.get("user_id", "")
    if not bot_user_id:
        print("auth.test returned no user_id")
        return 1

    now = datetime.now(timezone.utc)
    oldest = (now - timedelta(minutes=30)).timestamp()
    history = slack_api(
        "conversations.history",
        token,
        {
            "channel": channel_id,
            "oldest": f"{oldest:.6f}",
            "limit": 30,
        },
    )
    if not history.get("ok"):
        print(f"conversations.history failed: {history}")
        return 1

    messages = history.get("messages", [])
    messages_sorted = sorted(messages, key=lambda x: float(x.get("ts", "0")))
    summary_text = build_summary_text()

    reply_count = 0
    for message in messages_sorted:
        if message.get("subtype"):
            continue
        text = message.get("text", "")
        thread_ts = message.get("thread_ts") or message.get("ts")
        if not text or not thread_ts:
            continue
        if not should_reply(text, bot_user_id):
            continue
        if has_bot_reply(token, channel_id, thread_ts, bot_user_id):
            continue

        post = slack_api(
            "chat.postMessage",
            token,
            {
                "channel": channel_id,
                "thread_ts": thread_ts,
                "text": summary_text,
            },
        )
        if post.get("ok"):
            reply_count += 1
        else:
            print(f"chat.postMessage failed: {post}")

    print(f"mention responder completed. replies={reply_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
