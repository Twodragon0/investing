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

A second population joined 2026-09-04: blurbs left in English by the title-based
synthesizer. Neither the chrome check nor the title-duplicate check asks what
language a blurb is in, so 386 of them across 186 posts were invisible here even
though the sourcing order below is exactly what they need.

Sourcing order, mirroring the collection pipeline so a repaired blurb is
indistinguishable from a well-collected one:

1. **Re-fetch** the article URL (Google News redirects resolved first) and take
   its description, accepting it only if it passes the same quality gates a
   fresh collection would apply — not boilerplate, not a restatement of the
   title, long enough to inform.
2. **Translate** to Korean when the recovered text carries an English clause.
   The trigger is an embedded run of Hangul-free words, not "zero Hangul" — the
   leaked shape is "<English headline>. <Korean context>", which has Hangul in
   it. A translation that fails open is dropped, never written back.
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
import hashlib
import html
import json
import logging
import os
import re
import sys
import tempfile
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
from common.summary_quality import contains_english_clause, is_boilerplate, is_generic_desc  # noqa: E402
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
#
# Neither `title` nor `between` may cross into the next card. A card whose blurb
# was never emitted has a title but no `<p class="news-desc">`, and unconstrained
# `.*?` under `re.S` then walks past it and pairs that title -- and its URL --
# with the *next* card's blurb. Measured on the corpus 2026-09-09, by asking
# whether each match's anchor is the *nearest* one preceding its blurb: 109
# cards carry a title with no blurb, 97 of 5,515 blurbs were paired with an
# earlier card's title, and 25 of those were `_is_bad` flagged, i.e. inside this
# tool's target set. For those, `refetch` would have fetched the wrong article
# and written its summary over a blurb that belongs to a different headline --
# the contamination PR #1290 found by hand during the `--limit 20` rollout.
#
# Both constraints are load-bearing. Guarding `between` alone does not work:
# `title` is also `.*?` under `re.S`, so the engine backtracks and lets *it*
# swallow `</a>`, the blurb-less card's tail and the next card's whole anchor,
# reproducing the same wrong (url, desc) pair with the boundary now hidden
# inside `title`. Searching only `between` for `class="news-title"` reports zero
# violations in that state, which is why the guard test asserts the paired URL
# and title rather than counting boundary crossings.
_CARD_RE = re.compile(
    r'<a href="(?P<url>[^"]+)"[^>]*class="news-title"[^>]*>(?P<title>(?:(?!</a>).)*?)</a>'
    r'(?P<between>(?:(?!class="news-title").)*?)<p class="news-desc">(?P<desc>.*?)</p>',
    re.S,
)

# Alert-box entry: `<a href=...>title</a> <span class="p0-desc">blurb</span>`.
_P0_RE = re.compile(
    r'<a href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>\s*<span class="p0-desc">(?P<desc>.*?)</span>',
    re.S,
)

_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-")


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
    """A blurb worth replacing: site chrome, the headline restated, or English.

    The language arm was added 2026-09-04. Neither ``is_boilerplate`` nor the
    title-duplicate check asks what language a blurb is in, so the 252 blurbs
    the title-based synthesizer had emitted as
    "<English headline>. <entities> — <Korean context>" across 158 posts were
    invisible to this tool even though its sourcing order (re-fetch →
    translate → synthesize) is exactly what they need.
    """
    if not text:
        return True
    return is_boilerplate(text) or _is_desc_duplicate_of_title(text, title) or contains_english_clause(text)


# A blurb whose English words are mostly already in the card's title restates
# the headline. 0.5 is deliberately below `_is_desc_duplicate_of_title`'s bar:
# that check exists to reject an RSS artifact, this one to decide whether
# deleting loses anything, and a half-shared vocabulary means it does not.
_TITLE_OVERLAP_DROP_THRESHOLD = 0.5
_WORD_RE = re.compile(r"[A-Za-z]{3,}")
_FIRST_HANGUL_RE = re.compile(r"[가-힣]")

# Deletion has no per-item review step, so this bound is the only thing between
# a predicate regression and a mass delete. Sized to sit under the population
# the 2026-09-08 scan judged droppable (315) so a full sweep still takes several
# reviewed runs.
_MAX_DROPS_PER_RUN = 60


def _title_overlap(text: str, title: str) -> float:
    """Share of the blurb's English words that already appear in the title."""
    words = {w.lower() for w in _WORD_RE.findall(text)}
    if not words:
        return 0.0
    return len({w.lower() for w in _WORD_RE.findall(title)} & words) / len(words)


def _is_droppable(text: str, title: str) -> bool:
    """True when removing the blurb outright loses nothing the card still shows.

    Only reached for blurbs the resolver could not repair. The card keeps its
    Korean title, link and source, so the question is whether the blurb adds
    anything beyond those.

    Scoped to English leaks: a Korean blurb is never deleted here, whatever
    ``_is_bad`` thought of it.

    The hybrid arm requires the Hangul remainder to be *recognised filler*, not
    merely present. Measured over the 279 hybrid blurbs in ``_posts/`` on
    2026-09-08: 205 boilerplate tails + 53 generic tails, but **21 (7.5%) were
    real Korean prose quoting a long English proper-noun run**
    ("…Mario Tama/Getty Images John Rapley는 The Globe and Mail") — the residual
    false positive that ``ENGLISH_CLAUSE_MIN_WORDS = 6`` is documented to leave.
    "Has an English clause and some Hangul" would have deleted all 21.
    """
    if not text or not contains_english_clause(text):
        return False

    match = _FIRST_HANGUL_RE.search(text)
    if match:
        remainder = text[match.start() :]
        # Filler tail -> the English part is a pasted headline the Korean title
        # already carries. Substantive Korean -> keep it.
        return is_generic_desc(remainder) or is_boilerplate(remainder)

    # No Hangul at all: keep it unless it says nothing new. Distinct English
    # content is a translation job, not a deletion.
    return (
        is_boilerplate(text)
        or _is_desc_duplicate_of_title(text, title)
        or _title_overlap(text, title) >= _TITLE_OVERLAP_DROP_THRESHOLD
    )


def _cap_drops(candidates: list) -> list:
    """Bound one run's deletions to ``_MAX_DROPS_PER_RUN``."""
    return candidates[:_MAX_DROPS_PER_RUN]


def drop_from_post(content: str, old_raw: str, kind: str) -> tuple[str, bool]:
    """Remove a blurb's whole element, not just its inner text.

    Blanking the text would leave ``<p class="news-desc"></p>``, which renders
    as a gap in the card. The surrounding markup for the two blurb kinds is
    fixed by ``ThemedNewsRenderer``, so the element is reconstructed from the
    inner text rather than re-parsed.

    Refuses an ambiguous anchor for the same reason ``replace_in_post`` does:
    identical copies in one post point at different articles.
    """
    if kind == "news-desc":
        element = f'<p class="news-desc">{old_raw}</p>'
    elif kind == "p0-desc":
        element = f'<span class="p0-desc">{old_raw}</span>'
    else:
        return content, False

    occurrences = content.count(element)
    if occurrences != 1:
        return content, False
    # Take one adjacent newline with a card blurb so the element does not leave
    # a blank line inside `news-card-body`.
    if kind == "news-desc" and f"{element}\n" in content:
        return content.replace(f"{element}\n", "", 1), True
    return content.replace(element, "", 1), True


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


# ---------------------------------------------------------------------------
# Attempt memory
#
# `--limit` slices whatever order `collect_targets` returns, so under `newest`
# the daily job re-spends its whole request budget on whatever sits at the top
# -- and a blurb the resolver permanently cannot fix stays there forever.
# Measured 2026-09-09: the newest-200 window spanned 2026-08-06..09-09, leaving
# 2,403 flagged blurbs unreachable *at any yield*; the 2026-09-07 run failed 173
# of its 200, and 150 of the current window are those same August posts. New
# inflow is only ~6/day, so the window's composition is dominated by sticky
# failures rather than by fresh work.
#
# Reordering by defect class does not fix this -- title-duplicate is 1,546 of
# the 2,603 flagged, so a `title-dup-first` order moved `--limit 200` reach from
# 5 to 7 of a 36-blurb probe set. Remembering *what was already tried* is what
# makes the window advance.
# ---------------------------------------------------------------------------

_ATTEMPT_LOG_DEFAULT = REPO_ROOT / "_state" / "url_summary_attempts.json"

# Recorded outcome for "the resolver saw this and could not fix it". ``skipped``
# is deliberately never recorded: `--direct-only` skips Google News links
# without issuing a request, and counting that as an attempt would push a blurb
# the resolver never saw to the back of the queue -- the same `skipped` vs
# `unresolved` distinction that keeps `--drop-unresolvable` from deleting
# untried blurbs.
_ATTEMPT_UNRESOLVED = "unresolved"


def _attempt_key(blurb: Blurb) -> str:
    """Stable identity for one card across runs.

    Hashed rather than stored verbatim because Google News redirect URLs run to
    several hundred characters and the corpus carries ~2,600 flagged blurbs. The
    post name is stored alongside the hash so the file stays diagnosable.

    Keyed on (post, url) rather than on the blurb text: the text is what changes
    when a repair lands, and a repaired blurb stops being flagged anyway.
    """
    return hashlib.sha256(f"{blurb.path.name}\x00{blurb.url}".encode()).hexdigest()[:16]


def load_attempts(path: Path) -> dict[str, dict]:
    """Read the attempt log, or ``{}`` when there is nothing usable to read.

    Fail-open on purpose. This is a scheduling hint, not correctness: in CI the
    file arrives from ``actions/cache``, and a cache miss has to degrade to the
    previous ordering rather than abort the daily backfill. An empty log makes
    every blurb look untried, which `least-recently-tried` orders exactly like
    `newest`.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning("Attempt log unreadable, treating every blurb as untried: %s", e)
        return {}
    if not isinstance(raw, dict):
        logger.warning("Attempt log is %s, not an object; ignoring", type(raw).__name__)
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


def save_attempts(path: Path, attempts: dict[str, dict]) -> bool:
    """Write the log atomically. Returns ``False`` when the write did not land."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(attempts, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, str(path))
        tmp = None  # consumed by the rename
        return True
    except Exception as e:  # noqa: BLE001 - a log outage must not stop the backfill
        logger.warning("Attempt log save failed: %s", e)
        return False
    finally:
        # `os.replace` consumes the temp file on success; on any failure after
        # `mkstemp` it stayed behind. `common/translator.py` leaked four ~900KB
        # orphans into `_state/` exactly this way on 2026-09-07 (#1284).
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                logger.debug("Could not remove temp attempt log %s", tmp)


def record_attempts(
    attempts: dict[str, dict],
    repairs: list[tuple[Blurb, str, str]],
    today: date | None = None,
) -> int:
    """Fold this run's unresolved outcomes into ``attempts`` in place.

    Successes are not recorded: a repaired blurb stops being flagged, so it
    never reaches `collect_targets` again and a record would only grow the file.
    """
    stamp = (today or datetime.now(UTC).date()).isoformat()
    recorded = 0
    for blurb, text, source in repairs:
        if text or source != _ATTEMPT_UNRESOLVED:
            continue
        attempts[_attempt_key(blurb)] = {
            "tried": stamp,
            "outcome": _ATTEMPT_UNRESOLVED,
            "post": blurb.path.name,
        }
        recorded += 1
    return recorded


ORDER_NEWEST = "newest"
ORDER_DROPPABLE_FIRST = "droppable-first"
ORDER_LEAST_RECENTLY_TRIED = "least-recently-tried"
ORDERS = (ORDER_NEWEST, ORDER_DROPPABLE_FIRST, ORDER_LEAST_RECENTLY_TRIED)


def collect_targets(
    posts_dir: Path,
    days: int | None,
    order: str = ORDER_NEWEST,
    attempts: dict[str, dict] | None = None,
) -> list[Blurb]:
    """Flagged blurbs across the corpus.

    ``--limit`` slices whatever order this returns, so the order *is* the
    selection policy.

    ``newest`` (default) is what the daily scheduled job depends on and must not
    change without noticing. ``droppable-first`` moves deletable blurbs to the
    front while keeping newest-first inside each group, which is the only way a
    small ``--limit`` reaches the legacy population: those blurbs sit in
    2026-03..05, and from the newest end `--limit 60` reached 11 of them where
    droppable-first reaches 60 (measured 2026-09-08). It also explains why
    ``--days`` looked inert next to a small ``--limit`` — 90/180/365-day windows
    all selected the identical newest 60.

    ``least-recently-tried`` reads ``attempts`` (see the attempt-memory block
    above) and puts never-tried blurbs first, then the rest oldest-attempt
    first. With an empty or missing log every blurb looks untried, so it
    reproduces ``newest`` exactly -- that is the required behaviour on a CI
    cache miss, not an accident.

    Reordering does not change the resolver cost: Google News accounts for 86.3%
    of droppable blurbs and 88.9% of the rest, so the request profile is the
    same either way.
    """
    if order not in ORDERS:
        raise ValueError(f"unknown order {order!r}; expected one of {ORDERS}")

    cutoff = None if days is None else datetime.now(UTC).date() - timedelta(days=days)
    targets: list[Blurb] = []
    for path in sorted(posts_dir.glob("*.md"), reverse=True):
        posted = _post_date(path)
        if cutoff is not None and (posted is None or posted < cutoff):
            continue
        targets.extend(b for b in find_blurbs(path) if _is_bad(b.text, b.title))

    if order == ORDER_DROPPABLE_FIRST:
        # `sorted` is stable, so newest-first survives inside each group. That
        # matters for the staged rollout: an unstable order would hand a
        # different slice to every run and make reviewing one impossible.
        targets.sort(key=lambda b: not _is_droppable(b.text, b.title))
    elif order == ORDER_LEAST_RECENTLY_TRIED:
        log = attempts or {}
        # `""` for an untried blurb sorts ahead of every ISO date, so untried
        # goes first and the rest follow oldest-attempt first. Stable, so
        # newest-first survives inside each group.
        targets.sort(key=lambda b: log.get(_attempt_key(b), {}).get("tried", ""))
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

    # Trigger on an embedded English clause, not on "zero Hangul": a blurb that
    # leads with an English headline and trails a Korean sentence has Hangul in
    # it, so the old check skipped translation for exactly the shape this tool
    # was extended to repair.
    if contains_english_clause(desc):
        try:
            translated = translate_to_korean(desc)
        except Exception as exc:
            logger.debug("Translation failed, dropping English text: %s", exc)
            translated = ""
        # translate_to_korean is fail-open — it returns its input unchanged when
        # the service is disabled or errors. Re-check rather than trust, the
        # same contract headline.select_korean_headline uses. Without this a
        # failed translation writes the English text straight back: the blurb
        # stays flagged forever while the run reports it as repaired.
        if not translated or is_boilerplate(translated) or contains_english_clause(translated):
            return ""
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


def select_drops(repairs: list[tuple[Blurb, str, str]]) -> list[Blurb]:
    """Blurbs the resolver gave up on that are safe to delete outright.

    Only ``unresolved`` results are eligible: a blurb the resolver could still
    repair is repaired, never deleted. ``skipped`` is excluded too — that is
    "not attempted this run" (``--direct-only``), not "unrepairable".
    """
    candidates = [
        blurb
        for blurb, text, source in repairs
        if not text and source == "unresolved" and _is_droppable(blurb.text, blurb.title)
    ]
    return _cap_drops(candidates)


def apply_drops(drops: list[Blurb]) -> tuple[int, int]:
    """Delete blurb elements from disk, grouped per post.

    Returns ``(blurbs_dropped, posts_changed)``. Deliberately separate from
    ``apply_repairs`` so a run's deletions land in their own commit: the diff is
    then the record of what was removed, and one ``git revert`` restores all of
    it.
    """
    by_post: dict[Path, list[Blurb]] = {}
    for blurb in drops:
        by_post.setdefault(blurb.path, []).append(blurb)

    dropped = 0
    posts_changed = 0
    for path, items in by_post.items():
        content = path.read_text(encoding="utf-8", errors="replace")
        changed_here = 0
        for blurb in items:
            content, ok = drop_from_post(content, blurb.raw, blurb.kind)
            if ok:
                changed_here += 1
            else:
                logger.warning("Skipped ambiguous blurb anchor for drop in %s: %r", path.name, blurb.raw[:60])
        if changed_here:
            path.write_text(content, encoding="utf-8")
            dropped += changed_here
            posts_changed += 1
    return dropped, posts_changed


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


class _Parser(argparse.ArgumentParser):
    """Parser that rejects incoherent flag combinations at parse time.

    Validating here rather than in ``main`` keeps the rule reachable from a
    test: ``build_parser().parse_args([...])`` has to be the thing that fails,
    or the check can only be exercised by running the whole tool.
    """

    def parse_args(self, args=None, namespace=None):  # type: ignore[override]
        parsed = super().parse_args(args, namespace)
        if parsed.order == ORDER_DROPPABLE_FIRST and not parsed.drop_unresolvable:
            # Droppable-first pushes the newest posts' real-content blurbs past
            # `--limit`, and those are exactly the ones translation still has to
            # repair. Reordering without enabling deletion starves the tool's
            # primary mission for no gain.
            self.error("--order droppable-first requires --drop-unresolvable")
        return parsed


def build_parser() -> argparse.ArgumentParser:
    """The CLI parser, exposed so flag defaults are testable.

    Extracted from ``main`` because ``--drop-unresolvable`` defaulting to off
    is a safety property, and a test that cannot reach the parser can only
    skip — which proves nothing.
    """
    parser = _Parser(description="Backfill per-URL summaries in published posts.")
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
    parser.add_argument(
        "--order",
        choices=ORDERS,
        default=ORDER_NEWEST,
        help=(
            "대상 정렬. 기본 newest 는 최신순이며, 작은 --limit 과 함께 쓰면 영구 "
            "실패가 창 상단에 눌러앉아 예산을 재소비한다. droppable-first 는 삭제 "
            "적격을 앞으로 몰며 --drop-unresolvable 과 함께만 쓸 수 있다. "
            "least-recently-tried 는 --attempt-log 를 읽어 미시도 → 오래된 시도 순으로 "
            "정렬해 창을 전진시킨다 (일일 job 이 쓰는 값)"
        ),
    )
    parser.add_argument(
        "--attempt-log",
        type=Path,
        default=_ATTEMPT_LOG_DEFAULT,
        help=(
            "미해결 시도를 기록할 JSON 경로. --order least-recently-tried 가 이걸 읽는다. "
            "CI 에서는 actions/cache 로 런 간 유지되며 캐시 미스는 newest 동작으로 "
            "degrade 된다 (기본: _state/url_summary_attempts.json)"
        ),
    )
    parser.add_argument(
        "--drop-unresolvable",
        action="store_true",
        help=(
            f"재수집·번역이 모두 실패했고 카드가 이미 담고 있는 내용인 블러브를 삭제 "
            f"(런당 최대 {_MAX_DROPS_PER_RUN}건). 실질 콘텐츠는 삭제하지 않는다"
        ),
    )
    return parser


def main() -> int:
    parser = build_parser()
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

    # Loaded under every order, not just `least-recently-tried`: recording runs
    # unconditionally, so switching orders later inherits the history instead of
    # starting from an empty log.
    attempts = load_attempts(args.attempt_log)
    targets = collect_targets(POSTS_DIR, args.days, order=args.order, attempts=attempts)
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

    drops = select_drops(repairs) if args.drop_unresolvable else []
    if args.drop_unresolvable:
        unresolved = sum(1 for _b, text, source in repairs if not text and source == "unresolved")
        print(f"\n삭제 대상   : {len(drops)}건 (해결 실패 {unresolved}건 중, 런당 상한 {_MAX_DROPS_PER_RUN})")
        for blurb in drops[:3]:
            print(f"  [{blurb.path.name}] {blurb.text[:80]}")

    if args.apply:
        # Recorded before the writes so a throttled run -- which repairs nothing
        # and whose workflow step therefore commits nothing -- still advances the
        # window next time. That day is exactly when the record matters most.
        recorded = record_attempts(attempts, repairs)
        if recorded and save_attempts(args.attempt_log, attempts):
            print(f"\n시도 기록: 미해결 {recorded}건 (누적 {len(attempts)}건)")

        written, posts = apply_repairs(repairs)
        print(f"\n적용: 블러브 {written}건 / 포스트 {posts}개")
        if drops:
            # Written after the replacements so the two land in separate
            # commits when the caller commits between phases; the deletion diff
            # is the only record of removed text, so it must stay reviewable.
            dropped, drop_posts = apply_drops(drops)
            print(f"삭제: 블러브 {dropped}건 / 포스트 {drop_posts}개")
    else:
        print("\n(dry-run — 적용하려면 --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
