#!/usr/bin/env python3
"""Backfill per-URL summaries in published posts.

``fix_post_descriptions.py`` repairs a post's front-matter ``description``.
This tool repairs the layer underneath it: the per-article blurbs rendered
inside the post body (``<p class="news-desc">`` cards and ``<span class="p0-desc">``
alert entries).

That layer was never measured. The front-matter report reads 99.3% real
content, while a 2026-08-06 scan over 2309 posts / 4504 cards found ~758 blurbs
carrying site chrome instead of article content — outlet self-introductions,
market-data error notices, navigation bars, newsletter solicitations. The
detector strengthening that keeps *new* posts clean ships separately; this
backfills what is already published.

Sourcing order, mirroring the collection pipeline so a repaired blurb is
indistinguishable from a well-collected one:

1. **Re-fetch** the article URL (Google News redirects resolved first) and take
   its description, accepting it only if it passes the same quality gates a
   fresh collection would apply — not boilerplate, not a restatement of the
   title, long enough to inform.
2. **Translate** to Korean when the recovered text is not already Korean.
3. **Synthesize** from title + source when the fetch yields nothing usable
   (dead link, consent wall, paywall).

Sampling 10 flagged URLs before this was written gave 7 usable re-fetches, so
the fetch path carries the bulk.

**Run this incrementally.** 90% of flagged blurbs point at `news.google.com`
redirect links, and Google throttles the resolver hard: across three
back-to-back full passes the re-fetch yield fell 523 → 71 → 0, with the
resolver returning empty for every link by the third. Direct publisher URLs
kept working throughout, so the ceiling is the redirect resolver, not this
tool. Use `--limit` with a few hundred per run and space the runs out; a pass
that reports mostly "해결 실패" is a throttled pass, not a corpus without
recoverable summaries.

Usage:
    python scripts/fix_post_url_summaries.py                  # dry-run report
    python scripts/fix_post_url_summaries.py --days 30        # recent posts only
    python scripts/fix_post_url_summaries.py --apply          # write changes
    python scripts/fix_post_url_summaries.py --apply --limit 50
"""

from __future__ import annotations

import argparse
import html
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.config import setup_logging  # noqa: E402
from common.enrichment import _is_desc_duplicate_of_title  # noqa: E402
from common.enrichment_network import (  # noqa: E402
    _is_google_news_host,
    _resolve_google_news_url,
    fetch_page_metadata,
)
from common.enrichment_synthetic import (  # noqa: E402
    _is_title_related_description,
    generate_synthetic_description,
)
from common.summary_quality import is_boilerplate  # noqa: E402
from common.text_utils import _strip_trailing_artifacts, normalize_blurb  # noqa: E402
from common.translator import translate_to_korean  # noqa: E402

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = REPO_ROOT / "_posts"

# A recovered blurb shorter than this says less than the headline already does.
_MIN_DESC_LEN = 30

# …and longer than this is not a summary. `fetch_page_metadata` happily returns
# a whole article body when a page has no meta description; the first apply run
# put 400-800 character walls of text into cards sized for a sentence or two.
# Recovered text is trimmed back to a sentence boundary under this length.
_MAX_DESC_LEN = 300

# Sentence terminators used to trim without cutting mid-word.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?。])\s+|(?<=니다\.)\s*|(?<=습니다\.)\s*")

# Card blurb: the anchor and its `<p class="news-desc">` sit in the same card
# div, with the source tag and severity badge in between.
_CARD_RE = re.compile(
    r'<a href="(?P<url>[^"]+)"[^>]*class="news-title"[^>]*>(?P<title>.*?)</a>'
    r'(?P<between>.*?)<p class="news-desc">(?P<desc>.*?)</p>',
    re.S,
)

# Alert-box entry: `<a href=...>title</a> <span class="p0-desc">blurb</span>`.
_P0_RE = re.compile(
    r'<a href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>\s*<span class="p0-desc">(?P<desc>.*?)</span>',
    re.S,
)

_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-")
_HANGUL_RE = re.compile(r"[가-힣]")


class Blurb(NamedTuple):
    """One per-URL summary found in a post body."""

    path: Path
    kind: str  # "news-desc" | "p0-desc"
    url: str
    title: str
    raw: str  # the exact inner text to replace, as it appears on disk
    text: str  # unescaped, tag-stripped text for quality checks


def _plain(fragment: str) -> str:
    """Tag-stripped, entity-decoded text for quality checks."""
    return html.unescape(_TAG_RE.sub("", fragment)).strip()


def _post_date(path: Path) -> date | None:
    match = _DATE_RE.match(path.name)
    if not match:
        return None
    try:
        return date(*(int(g) for g in match.groups()))
    except ValueError:
        return None


def _is_bad(text: str, title: str) -> bool:
    """A blurb worth replacing: site chrome, or the headline restated."""
    if not text:
        return True
    return is_boilerplate(text) or _is_desc_duplicate_of_title(text, title)


def find_blurbs(path: Path) -> list[Blurb]:
    """Every per-URL summary in a post, flagged or not."""
    text = path.read_text(encoding="utf-8", errors="replace")
    found: list[Blurb] = []
    for kind, pattern in (("news-desc", _CARD_RE), ("p0-desc", _P0_RE)):
        for match in pattern.finditer(text):
            found.append(
                Blurb(
                    path=path,
                    kind=kind,
                    url=match.group("url"),
                    title=_plain(match.group("title")),
                    raw=match.group("desc"),
                    text=_plain(match.group("desc")),
                )
            )
    return found


def collect_targets(posts_dir: Path, days: int | None) -> list[Blurb]:
    """Flagged blurbs across the corpus, newest post first."""
    cutoff = None if days is None else datetime.now(UTC).date() - timedelta(days=days)
    targets: list[Blurb] = []
    for path in sorted(posts_dir.glob("*.md"), reverse=True):
        posted = _post_date(path)
        if cutoff is not None and (posted is None or posted < cutoff):
            continue
        targets.extend(b for b in find_blurbs(path) if _is_bad(b.text, b.title))
    return targets


# Exactly two periods. `...` is deliberate Korean punctuation and must survive;
# `..` is the artefact of appending a terminator to text that already had one.
_DOUBLED_PERIOD_RE = re.compile(r"(?<!\.)\.\.(?!\.)")


def clean_text(text: str) -> str:
    """Deterministic text repairs for one blurb, or ``""`` when it is already fine.

    No network: this pass fixes what is wrong with the *text as written*, which
    is why it can run while the Google News resolver is throttled and why it
    looks at every blurb rather than only the flagged ones.

    Returning ``""`` for a clean blurb is load-bearing — callers use it to skip
    the rewrite entirely rather than writing the same bytes back.
    """
    cleaned = normalize_blurb(text)
    return cleaned if cleaned != text.strip() else ""


_ALERT_BOX_RE = re.compile(r'<div class="alert-box alert-urgent">.*?</div>', re.S)
_P0_LINK_RE = re.compile(r'<li><a href="(?P<url>[^"]+)">(?P<title>.*?)</a>', re.S)
_CARD_LINK_RE = re.compile(r'<a href="(?P<url>[^"]+)"[^>]*class="news-title"[^>]*>(?P<title>.*?)</a>', re.S)


def recover_p0_links(path: Path) -> int:
    """Repoint homepage p0 links at the article, using the post's own cards.

    `<source url>` in Google News RSS names the publisher, and the renderer
    preferred it over the item's real link, so 267 published p0 alerts point at
    a front page instead of the story. The original URL was overwritten before
    render and is not in `_state` (a dedup hash store), so it survives only
    where the same story also appears as a theme card in the same post — 54 of
    267 (20%).

    Exact title match only. Prefix matching recovered just one more across the
    corpus while risking a pairing with the wrong story, which is the failure
    this whole thread has been cleaning up after.
    """
    content = path.read_text(encoding="utf-8", errors="replace")
    cards: dict[str, str] = {}
    for match in _CARD_LINK_RE.finditer(content):
        cards.setdefault(_plain(match.group("title")), match.group("url"))

    replacements: list[tuple[str, str]] = []
    for box in _ALERT_BOX_RE.finditer(content):
        for match in _P0_LINK_RE.finditer(box.group(0)):
            url = match.group("url")
            if _has_article_path(url):
                continue
            article = cards.get(_plain(match.group("title")))
            if article and _has_article_path(article):
                replacements.append((match.group(0), match.group(0).replace(url, article, 1)))

    if not replacements:
        return 0
    for old, new in replacements:
        content = content.replace(old, new, 1)
    path.write_text(content, encoding="utf-8")
    return len(replacements)


def collect_text_targets(posts_dir: Path, days: int | None) -> list:
    """``(blurb, replacement)`` for every blurb the text pass would change.

    Scans *all* blurbs, not just ones failing the quality gate: a summary can
    be accurate and still carry a duplicated outlet name.
    """
    cutoff = None if days is None else datetime.now(UTC).date() - timedelta(days=days)
    targets: list = []
    for path in sorted(posts_dir.glob("*.md"), reverse=True):
        posted = _post_date(path)
        if cutoff is not None and (posted is None or posted < cutoff):
            continue
        for blurb in find_blurbs(path):
            replacement = clean_text(blurb.text)
            if replacement:
                targets.append((blurb, replacement))
    return targets


def _resolve(url: str) -> str:
    """Follow a Google News redirect to the publisher, best effort.

    Host is parsed rather than substring-matched, so an article URL that merely
    mentions ``news.google.com`` in its path or query is not misrouted through
    the redirect resolver (CodeQL ``py/incomplete-url-substring-sanitization``).
    """
    if not _is_google_news_host(url):
        return url
    try:
        resolved = _resolve_google_news_url(url)
    except Exception as exc:  # network/parse failures are expected on old links
        logger.debug("Google News resolve failed for %s: %s", url[:60], exc)
        return ""
    return resolved if resolved and not _is_google_news_host(resolved) else ""


def _has_article_path(url: str) -> bool:
    """False for a bare domain — a homepage, not an article.

    Re-fetching `https://www.sedaily.com` returns whatever is on the front page
    at that moment, so the recovered "summary" describes a different story. The
    first scheduled run did exactly that to one p0 blurb; 155 of 2272 targets
    carry such links. A query string still identifies a specific item, so it
    counts as a path.
    """
    parsed = urlparse(url)
    return bool(parsed.path.strip("/") or parsed.query)


def refetch(blurb: Blurb) -> str:
    """A usable replacement from the live article, or "" if none.

    Applies the gates a fresh collection would: not boilerplate, not a
    restatement of the headline, related to the headline, long enough.
    """
    if not _has_article_path(blurb.url):
        return ""
    link = _resolve(blurb.url)
    if not link or not _has_article_path(link):
        return ""
    try:
        meta = fetch_page_metadata(link, title=blurb.title)
    except Exception as exc:
        logger.debug("Fetch failed for %s: %s", link[:60], exc)
        return ""

    # Unescape first: fetched text carries raw entities (`&hellip;`, `&amp;`).
    # Writing it back without this produced `&amp;hellip;` on the page — the
    # entity rendered as literal text instead of the character it names.
    desc = html.unescape((meta or {}).get("description", "")).strip()
    # Ad tails ride along with fetched copy ("Priority Gold에서 무료 가이드 받기").
    # Delegated to the canonical stripper the quality checker already uses.
    desc = _trim_to_sentence(_strip_trailing_artifacts(desc))
    if len(desc) < _MIN_DESC_LEN:
        return ""
    if is_boilerplate(desc) or _is_desc_duplicate_of_title(desc, blurb.title):
        return ""
    if not _is_title_related_description(blurb.title, desc):
        return ""

    if not _HANGUL_RE.search(desc):
        try:
            translated = translate_to_korean(desc)
        except Exception as exc:
            logger.debug("Translation failed, keeping source text: %s", exc)
            translated = ""
        if translated and not is_boilerplate(translated):
            desc = translated

    return desc


def _trim_to_sentence(text: str, limit: int = _MAX_DESC_LEN) -> str:
    """Cut ``text`` back to the last sentence boundary at or under ``limit``.

    Falls back to a hard cut with an ellipsis when the first sentence alone
    already exceeds the limit, so a run-on page never lands whole in a card.
    """
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    head = text[:limit]
    boundaries = [m.end() for m in _SENTENCE_END_RE.finditer(head)]
    if boundaries and boundaries[-1] >= _MIN_DESC_LEN:
        return head[: boundaries[-1]].strip()
    return head.rstrip() + "…"


def synthesize(blurb: Blurb) -> str:
    """Fact-based fallback built from the headline when the link is unusable."""
    try:
        return generate_synthetic_description(blurb.title, "", None).strip()
    except Exception as exc:
        logger.debug("Synthesis failed for %r: %s", blurb.title[:60], exc)
        return ""


def replace_in_post(content: str, old_raw: str, new_text: str, all_copies: bool = False) -> tuple[str, bool]:
    """Swap one blurb's inner text, leaving the surrounding markup untouched.

    The replacement is HTML-escaped because it lands inside an element body.

    By default it is applied only when ``old_raw`` occurs exactly once: a blurb
    repeated verbatim in the same post would otherwise have every copy
    rewritten from one URL's fetch, and those copies point at different
    articles.

    ``all_copies`` lifts that restriction for the text pass, where the
    replacement is a pure function of the text itself — every identical copy
    has the same correct rewrite, so refusing to touch them just leaves known
    defects on the page. Measured: 18 of 106 text targets were skipped as
    "ambiguous" before this existed.
    """
    occurrences = content.count(old_raw)
    if occurrences == 0 or (occurrences > 1 and not all_copies):
        return content, False
    escaped = html.escape(new_text, quote=False)
    count = -1 if all_copies else 1
    return content.replace(old_raw, escaped, count), True


def is_google_news(blurb: Blurb) -> bool:
    """True when the blurb's link is a Google News redirect rather than an article."""
    return _is_google_news_host(blurb.url)


def _repair_one(blurb: Blurb, allow_synthesis: bool = True, direct_only: bool = False) -> tuple[Blurb, str, str]:
    """Resolve a replacement for one blurb. Returns (blurb, text, source)."""
    if direct_only and is_google_news(blurb):
        return blurb, "", "skipped"
    recovered = refetch(blurb)
    if recovered:
        return blurb, recovered, "refetch"
    if not allow_synthesis:
        return blurb, "", "unresolved"
    synthetic = synthesize(blurb)
    if synthetic and not _is_bad(synthetic, blurb.title):
        return blurb, synthetic, "synthetic"
    return blurb, "", "unresolved"


def repair(
    targets: list[Blurb],
    workers: int,
    allow_synthesis: bool = True,
    direct_only: bool = False,
) -> list[tuple[Blurb, str, str]]:
    """Resolve replacements concurrently, preserving input order."""
    results: list[tuple[Blurb, str, str] | None] = [None] * len(targets)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_repair_one, b, allow_synthesis, direct_only): i for i, b in enumerate(targets)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result(timeout=60)
            except Exception as exc:
                logger.debug("Repair failed for %s: %s", targets[index].url[:60], exc)
                results[index] = (targets[index], "", "unresolved")
    return [r for r in results if r is not None]


def apply_repairs(repairs: list[tuple[Blurb, str, str]], all_copies: bool = False) -> tuple[int, int]:
    """Write resolved replacements to disk, grouped per post.

    Returns ``(blurbs_written, posts_changed)``. Ambiguous anchors are skipped
    rather than guessed at.
    """
    by_post: dict[Path, list[tuple[Blurb, str]]] = {}
    for blurb, text, _source in repairs:
        if text:
            by_post.setdefault(blurb.path, []).append((blurb, text))

    written = 0
    posts_written = 0
    for path, items in by_post.items():
        content = path.read_text(encoding="utf-8", errors="replace")
        changed_here = 0
        for blurb, text in items:
            content, ok = replace_in_post(content, blurb.raw, text, all_copies=all_copies)
            if ok:
                changed_here += 1
            else:
                logger.warning("Skipped ambiguous blurb anchor in %s: %r", path.name, blurb.raw[:60])
        if changed_here:
            path.write_text(content, encoding="utf-8")
            written += changed_here
            posts_written += 1
    return written, posts_written


def format_report(repairs: list[tuple[Blurb, str, str]], applied: bool) -> str:
    """Human-readable summary with a sample of each outcome."""
    total = len(repairs)
    counts = {"refetch": 0, "synthetic": 0, "unresolved": 0, "skipped": 0}
    for _blurb, _text, source in repairs:
        counts[source] = counts.get(source, 0) + 1

    lines = [
        f"URL 요약 백필 {'적용' if applied else '(dry-run)'}",
        f"  대상 블러브   : {total}",
        f"  재수집 성공   : {counts['refetch']}",
        f"  합성 대체     : {counts['synthetic']}",
        f"  해결 실패     : {counts['unresolved']}",
        f"  건너뜀        : {counts['skipped']}",
    ]

    for source in ("refetch", "synthetic"):
        samples = [(b, t) for b, t, s in repairs if s == source][:3]
        if not samples:
            continue
        lines.append(f"\n  --- {source} 샘플 ---")
        for blurb, text in samples:
            lines.append(f"  [{blurb.path.name}] {blurb.title[:60]}")
            lines.append(f"    before: {blurb.text[:80]}")
            lines.append(f"    after : {text[:80]}")
    return "\n".join(lines)


def _run_text_only(args) -> int:
    """Deterministic text pass — no fetching, no synthesis."""
    targets = collect_text_targets(POSTS_DIR, args.days)
    if args.limit is not None:
        targets = targets[: args.limit]
    if not targets:
        print("텍스트 교정 대상 없음.")
        return 0

    print(f"텍스트 교정 {'적용' if args.apply else '(dry-run)'}: {len(targets)}건")
    for blurb, replacement in targets[:5]:
        print(f"  [{blurb.path.name}]\n    before: {blurb.text[:78]}\n    after : {replacement[:78]}")

    if not args.apply:
        print("\n(dry-run — 적용하려면 --apply)")
        return 0

    written, posts = apply_repairs([(b, r, "text") for b, r in targets], all_copies=True)
    print(f"\n적용: 블러브 {written}건 / 포스트 {posts}개")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill per-URL summaries in published posts.")
    parser.add_argument("--days", type=int, default=None, help="최근 N일 포스트만 (기본: 전체)")
    parser.add_argument("--limit", type=int, default=None, help="처리할 블러브 최대 개수")
    parser.add_argument("--workers", type=int, default=6, help="동시 재수집 스레드 수 (기본 6)")
    parser.add_argument("--apply", action="store_true", help="실제 파일에 기록 (기본: dry-run)")
    parser.add_argument(
        "--recover-p0-links",
        action="store_true",
        help="홈페이지로 향하는 p0 링크를 같은 포스트 카드의 기사 링크로 교정 (네트워크 불필요)",
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="네트워크 없이 텍스트 결함만 결정적으로 교정 (출처 접미사·중복 마침표)",
    )
    parser.add_argument(
        "--direct-only",
        action="store_true",
        help="Google News 리다이렉트는 건너뛰고 직접 퍼블리셔 URL 만 처리 (스로틀 중 유용)",
    )
    parser.add_argument(
        "--skip-synthetic",
        action="store_true",
        help="재수집 실패 시 합성 폴백을 쓰지 않고 원문 유지 (품질 저하 방지)",
    )
    args = parser.parse_args()

    setup_logging()

    if args.recover_p0_links:
        total = 0
        changed = 0
        for path in sorted(POSTS_DIR.glob("*.md")):
            if not args.apply:
                continue
            fixed = recover_p0_links(path)
            if fixed:
                total += fixed
                changed += 1
        if not args.apply:
            print("(dry-run — 적용하려면 --apply)")
            return 0
        print(f"p0 링크 복구: {total}건 / 포스트 {changed}개")
        return 0

    if args.text_only:
        return _run_text_only(args)

    targets = collect_targets(POSTS_DIR, args.days)
    if args.limit is not None:
        targets = targets[: args.limit]

    if not targets:
        print("불량 URL 요약 없음.")
        return 0

    logger.info("Repairing %d flagged blurbs with %d workers", len(targets), args.workers)
    repairs = repair(
        targets,
        args.workers,
        allow_synthesis=not args.skip_synthetic,
        direct_only=args.direct_only,
    )

    print(format_report(repairs, applied=args.apply))

    if args.apply:
        written, posts = apply_repairs(repairs)
        print(f"\n적용: 블러브 {written}건 / 포스트 {posts}개")
    else:
        print("\n(dry-run — 적용하려면 --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
