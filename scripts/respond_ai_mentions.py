#!/usr/bin/env python3

import json
import os
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from glob import glob
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "_posts"
SLACK_API_BASE = "https://slack.com/api"
CHANNEL_ALIASES = ("ops", "dev", "ai", "investing")


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


def build_dev_status_text() -> str:
    try:
        commit = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%h %s"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        commit = "unknown"

    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        branch = "main"

    return "\n".join(
        [
            "개발 채널 기준 상태입니다.",
            f"- branch: {branch}",
            f"- latest commit: {commit}",
            "- CI/배포 상태는 GitHub Actions 탭에서 확인해 주세요.",
        ]
    )


def build_ops_status_text() -> str:
    daily_summary = latest_post("*daily-news-summary*.md")
    latest = daily_summary.name if daily_summary else "none"
    return "\n".join(
        [
            "운영 채널 기준 상태입니다.",
            f"- latest summary file: {latest}",
            "- site: https://investing.2twodragon.com/",
            "- 배포/헬스체크 이슈는 Actions run 로그를 우선 확인해 주세요.",
        ]
    )


def channel_id_for_alias(alias: str) -> str:
    upper = alias.upper()
    if alias == "investing":
        return env_first(
            "SLACK_CHANNEL_ID_INVESTING",
            "AI_SLACK_CHANNEL_ID_INVESTING",
            "SLACK_CHANNEL_INVESTING",
            "SLACK_CHANNEL_ID",
            "AI_SLACK_CHANNEL_ID",
            "SLACK_CHANNEL",
        )
    return env_first(
        f"SLACK_CHANNEL_ID_{upper}",
        f"AI_SLACK_CHANNEL_ID_{upper}",
        f"SLACK_CHANNEL_{upper}",
        "SLACK_CHANNEL_ID",
        "AI_SLACK_CHANNEL_ID",
        "SLACK_CHANNEL",
    )


def intent_keywords(alias: str) -> List[str]:
    if alias == "ops":
        return ["ops", "운영", "상태", "배포", "헬스", "장애", "status"]
    if alias == "dev":
        return ["dev", "개발", "빌드", "ci", "배포", "commit", "릴리즈"]
    return [
        "투자",
        "요약",
        "소식",
        "summary",
        "market",
        "news",
        "브리핑",
        "코인",
        "crypto",
        "실시간",
        "realtime",
        "monitor",
        "모니터링",
        "price",
    ]


def wants_coin_monitoring(text: str) -> bool:
    lowered = text.lower()
    return any(
        key in lowered
        for key in [
            "실시간",
            "realtime",
            "monitor",
            "모니터링",
            "코인",
            "crypto",
            "price",
        ]
    )


def build_coin_monitoring_text() -> str:
    market_report = latest_post("*daily-market-report*.md")
    if market_report:
        slug = market_report.stem
        parts = slug.split("-", 3)
        if len(parts) == 4:
            report_link = f"https://investing.2twodragon.com/market-analysis/{parts[0]}/{parts[1]}/{parts[2]}/{parts[3]}/"
        else:
            report_link = "https://investing.2twodragon.com/"
    else:
        report_link = "https://investing.2twodragon.com/"

    return "\n".join(
        [
            "실시간 코인 모니터링 요청 확인했습니다.",
            "- 최신 시장 리포트: " + report_link,
            "- CoinGecko: https://www.coingecko.com/",
            "- CoinMarketCap: https://coinmarketcap.com/",
            "- 5분 주기로 멘션을 확인해 후속 요청에 답변합니다.",
        ]
    )


def build_reply_text(alias: str, text: str) -> str:
    if alias == "ops":
        return build_ops_status_text()
    if alias == "dev":
        return build_dev_status_text()
    if wants_coin_monitoring(text):
        return build_coin_monitoring_text()
    return build_summary_text()


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


def should_reply(text: str, bot_user_id: str, alias: str) -> bool:
    lowered = text.lower()
    mention_token = f"<@{bot_user_id}>".lower()
    has_mention = mention_token in lowered or "ai" in lowered
    return has_mention


def fallback_help_text(alias: str) -> str:
    if alias in ("ai", "investing"):
        return "예: '@AI 실시간 코인 모니터링 해줘', '@AI 오늘 투자 소식 요약해줘'"
    if alias == "ops":
        return "예: '@AI 운영 상태 확인해줘', '@AI 배포 상태 알려줘'"
    return "예: '@AI dev 상태 알려줘', '@AI 최신 커밋 요약해줘'"


def main() -> int:
    alias = os.getenv("TARGET_CHANNEL_ALIAS", "investing").strip().lower()
    if alias not in CHANNEL_ALIASES:
        print(f"Unsupported alias: {alias}")
        return 1

    token = env_first("SLACK_BOT_TOKEN", "AI_SLACK_BOT_TOKEN", "SLACK_TOKEN")
    channel_id = channel_id_for_alias(alias)

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
    reply_text_default = build_reply_text(alias, "")

    reply_count = 0
    for message in messages_sorted:
        if message.get("subtype"):
            continue
        text = message.get("text", "")
        thread_ts = message.get("thread_ts") or message.get("ts")
        if not text or not thread_ts:
            continue
        if not should_reply(text, bot_user_id, alias):
            continue
        if has_bot_reply(token, channel_id, thread_ts, bot_user_id):
            continue

        has_intent = any(key in text.lower() for key in intent_keywords(alias))
        reply_text = (
            build_reply_text(alias, text) if has_intent else fallback_help_text(alias)
        )

        post = slack_api(
            "chat.postMessage",
            token,
            {
                "channel": channel_id,
                "thread_ts": thread_ts,
                "text": reply_text or reply_text_default,
            },
        )
        if post.get("ok"):
            reply_count += 1
        else:
            print(f"chat.postMessage failed: {post}")

    print(f"mention responder completed. alias={alias} replies={reply_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
