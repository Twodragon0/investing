import importlib.util
from pathlib import Path

module_path = Path(__file__).resolve().parents[1] / "scripts" / "respond_ai_mentions.py"
spec = importlib.util.spec_from_file_location("respond_ai_mentions", module_path)
assert spec is not None
assert spec.loader is not None
respond_ai_mentions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(respond_ai_mentions)
should_reply = respond_ai_mentions.should_reply


def test_should_reply_when_direct_slack_mention():
    assert should_reply("<@U123> 상태 알려줘", "U123", "ops") is True


def test_should_reply_when_uppercase_AI_word_standalone():
    # After commit e1e99acd (tighten ai mention reply gating), only the
    # uppercase abbreviation "AI" triggers a reply — lowercase "ai" is
    # too ambiguous (matches substrings like "mail", "paid", etc.).
    assert should_reply("AI 오늘 요약해줘", "U123", "investing") is True


def test_should_not_reply_for_lowercase_ai_word():
    # Lowercase ai no longer triggers a reply — intentional narrowing.
    assert should_reply("ai 오늘 요약해줘", "U123", "investing") is False


def test_should_reply_when_openclaw_question():
    # openclaw keyword now requires a question mark to signal ask intent.
    assert should_reply("openclaw 시장 브리핑 해줘?", "U123", "investing") is True


def test_should_not_reply_when_openclaw_without_question():
    assert should_reply("openclaw 시장 브리핑", "U123", "investing") is False


def test_should_not_reply_for_non_mention_text():
    assert should_reply("오늘은 paid plan만 점검", "U123", "investing") is False
