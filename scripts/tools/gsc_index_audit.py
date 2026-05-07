#!/usr/bin/env python3
"""Google Search Console Index Audit.

Inspect every URL from the sitemap (or a custom list) via the URL Inspection
API and produce an actionable Markdown report bucketed by coverage state.

Setup (same as gsc_api.py)
--------------------------
1. GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
2. Service account must have "Owner" permission in GSC
   (URL Inspection API requires Owner level)

Usage
-----
  # Audit all URLs from the sitemap (default output: reports/gsc-audit-YYYY-MM-DD.md)
  python scripts/tools/gsc_index_audit.py --from-sitemap

  # Limit to first 50 URLs for a quick test
  python scripts/tools/gsc_index_audit.py --from-sitemap --limit 50

  # Custom output path
  python scripts/tools/gsc_index_audit.py --from-sitemap --output reports/my-audit.md

  # Ad-hoc inspection of specific URLs
  python scripts/tools/gsc_index_audit.py --urls https://investing.2twodragon.com/ https://investing.2twodragon.com/about/

  # Slower rate (safer under quota pressure)
  python scripts/tools/gsc_index_audit.py --from-sitemap --sleep 0.5

  # Cap examples per state (avoid 2000-row reports)
  python scripts/tools/gsc_index_audit.py --from-sitemap --max-per-state 30

Quota notes
-----------
- URL Inspection API: ~2 000 inspections/day, 600/minute.
- Default --sleep 0.2 s → ~5 req/s. For 974 URLs: ~3-4 minutes.
- If you hit 429, the script backs off with a longer sleep and retries.

Dependencies
------------
  pip install google-api-python-client google-auth
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from config import REQUEST_TIMEOUT, get_env, setup_logging  # noqa: E402

logger = setup_logging("gsc_index_audit")

# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_SITE_URL = "https://investing.2twodragon.com/"
SITEMAP_URL = "https://investing.2twodragon.com/sitemap.xml"
LOCAL_SITEMAP = Path(__file__).resolve().parents[2] / "_site" / "sitemap.xml"

# Coverage state → bucket mapping.  Keys are exact strings from the API.
_BUCKET_MAP: dict[str, str] = {
    "Submitted and indexed": "INDEXED",
    "Indexed, not submitted in sitemap": "INDEXED",
    "Discovered - currently not indexed": "DISCOVERED_NOT_INDEXED",
    "Crawled - currently not indexed": "CRAWLED_NOT_INDEXED",
    "Not found (404)": "NOT_FOUND_404",
    "Page with redirect": "REDIRECT",
    "Blocked by robots.txt": "BLOCKED",
    "Blocked due to access forbidden (403)": "BLOCKED",
}

# Ordered display sequence for the report
_BUCKET_ORDER = [
    "NOT_FOUND_404",
    "DISCOVERED_NOT_INDEXED",
    "CRAWLED_NOT_INDEXED",
    "REDIRECT",
    "BLOCKED",
    "OTHER",
    "INDEXED",
]

_BUCKET_LABELS = {
    "NOT_FOUND_404": "404 Not Found",
    "DISCOVERED_NOT_INDEXED": "Discovered – Not Indexed",
    "CRAWLED_NOT_INDEXED": "Crawled – Not Indexed",
    "REDIRECT": "Page with Redirect",
    "BLOCKED": "Blocked (robots / 403)",
    "OTHER": "Other / Unknown",
    "INDEXED": "Indexed",
}

_MAX_CONSECUTIVE_FAILURES = 50
_QUOTA_SLEEP = 60.0  # seconds to wait after a 429 response

# ── Google API helpers (mirrors gsc_api.py pattern) ──────────────────────────


def _require_googleapi() -> tuple[Any, Any]:
    """Import google-api-python-client lazily with a clear error on failure."""
    try:
        from google.oauth2 import service_account  # type: ignore[import-untyped]
        from googleapiclient.discovery import build  # type: ignore[import-untyped]
    except ImportError as exc:
        logger.error(
            "missing dependency — install with: pip install google-api-python-client google-auth (%s)",
            exc,
        )
        sys.exit(2)
    return service_account, build


def _build_service() -> Any:
    """Authenticate with the service account and return the GSC client."""
    cred_path = get_env("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not cred_path:
        logger.error(
            "GOOGLE_APPLICATION_CREDENTIALS env var is not set. "
            "Point it at your service-account JSON file."
        )
        sys.exit(2)
    if not Path(cred_path).is_file():
        logger.error("credentials file not found: %s", cred_path)
        sys.exit(2)

    service_account, build = _require_googleapi()
    creds = service_account.Credentials.from_service_account_file(
        cred_path,
        scopes=["https://www.googleapis.com/auth/webmasters"],
    )
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


# ── Sitemap loading ───────────────────────────────────────────────────────────


def _load_sitemap_urls() -> list[str]:
    """Load URLs from local _site/sitemap.xml or fall back to the live URL."""
    if LOCAL_SITEMAP.is_file():
        logger.info("Reading sitemap from local file: %s", LOCAL_SITEMAP)
        tree = ET.parse(LOCAL_SITEMAP)  # noqa: S314 — local file, not untrusted input
        root = tree.getroot()
    else:
        logger.info("Local sitemap not found — downloading from %s", SITEMAP_URL)
        try:
            with urllib.request.urlopen(SITEMAP_URL, timeout=REQUEST_TIMEOUT) as resp:  # noqa: S310
                content = resp.read()
        except Exception as exc:
            logger.error("Failed to download sitemap: %s", exc)
            sys.exit(1)
        root = ET.fromstring(content)  # noqa: S314 — trusted own site

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls: list[str] = []
    for loc in root.findall(".//sm:loc", ns):
        text = (loc.text or "").strip()
        if text:
            urls.append(text)

    if not urls:
        # Try without namespace
        for loc in root.findall(".//loc"):
            text = (loc.text or "").strip()
            if text:
                urls.append(text)

    logger.info("Loaded %d URLs from sitemap", len(urls))
    return urls


# ── URL category extraction ───────────────────────────────────────────────────


def _extract_category(url: str) -> str:
    """Return the first non-empty path segment, e.g. 'crypto-news' from the URL."""
    path = url.split("://", 1)[-1]  # strip scheme
    path = path.split("/", 1)[-1] if "/" in path else ""  # strip host
    segment = path.strip("/").split("/")[0] if path.strip("/") else ""
    return segment or "(root)"


# ── Inspection ────────────────────────────────────────────────────────────────


def _classify(coverage_state: str) -> str:
    """Map a raw coverageState string to an internal bucket name."""
    return _BUCKET_MAP.get(coverage_state, "OTHER")


def _inspect_urls(
    service: Any,
    urls: list[str],
    site_url: str,
    sleep_s: float,
    max_per_state: int,
) -> dict[str, list[dict[str, str]]]:
    """Inspect each URL and collect results bucketed by coverage state.

    Returns a dict of bucket_name → list of result dicts.
    Continues on per-URL failure; aborts after _MAX_CONSECUTIVE_FAILURES.
    """
    buckets: dict[str, list[dict[str, str]]] = defaultdict(list)
    consecutive_failures = 0
    total = len(urls)

    for idx, url in enumerate(urls, 1):
        logger.info("[%d/%d] Inspecting %s", idx, total, url)

        try:
            resp = service.urlInspection().index().inspect(
                body={
                    "inspectionUrl": url,
                    "siteUrl": site_url,
                    "languageCode": "ko-KR",
                }
            ).execute()
            consecutive_failures = 0
        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "Quota" in exc_str or "quota" in exc_str:
                logger.warning("Quota/rate-limit hit — sleeping %.0fs before retry", _QUOTA_SLEEP)
                time.sleep(_QUOTA_SLEEP)
                # Retry once
                try:
                    resp = service.urlInspection().index().inspect(
                        body={
                            "inspectionUrl": url,
                            "siteUrl": site_url,
                            "languageCode": "ko-KR",
                        }
                    ).execute()
                    consecutive_failures = 0
                except Exception as exc2:
                    logger.warning("Retry failed for %s: %s", url, exc2)
                    consecutive_failures += 1
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        logger.error(
                            "Aborting: %d consecutive failures — likely auth or quota issue",
                            consecutive_failures,
                        )
                        break
                    time.sleep(sleep_s)
                    continue
            else:
                logger.warning("Inspection failed for %s: %s", url, exc)
                consecutive_failures += 1
                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    logger.error(
                        "Aborting: %d consecutive failures — likely auth or quota issue",
                        consecutive_failures,
                    )
                    break
                time.sleep(sleep_s)
                continue

        isr = resp.get("inspectionResult", {}).get("indexStatusResult", {})
        coverage_state = isr.get("coverageState", "")
        verdict = isr.get("verdict", "")
        last_crawl = isr.get("lastCrawlTime", "")
        google_canonical = isr.get("googleCanonical", "")
        robots_txt_state = isr.get("robotsTxtState", "")
        indexing_state = isr.get("indexingState", "")

        bucket = _classify(coverage_state)

        if bucket == "OTHER" and coverage_state:
            logger.info("Unmapped coverageState %r for %s — placed in OTHER bucket", coverage_state, url)

        # Respect max_per_state cap (only affects storage, not logging)
        if max_per_state <= 0 or len(buckets[bucket]) < max_per_state:
            buckets[bucket].append(
                {
                    "url": url,
                    "coverageState": coverage_state,
                    "verdict": verdict,
                    "lastCrawlTime": last_crawl,
                    "googleCanonical": google_canonical,
                    "robotsTxtState": robots_txt_state,
                    "indexingState": indexing_state,
                }
            )

        time.sleep(sleep_s)

    return dict(buckets)


# ── Report generation ─────────────────────────────────────────────────────────


def _build_report(
    buckets: dict[str, list[dict[str, str]]],
    all_urls: list[str],
    inspected_count: int,
    max_per_state: int,
    audit_date: str,
) -> str:
    total_inspected = inspected_count
    total_stored = sum(len(v) for v in buckets.values())

    lines: list[str] = []
    lines.append(f"# GSC Index Audit — {audit_date}")
    lines.append("")
    lines.append(
        f"Inspected **{total_inspected}** of **{len(all_urls)}** sitemap URLs "
        f"(stored up to {max_per_state} examples per state)."
    )
    lines.append("")

    # ── Summary table ────────────────────────────────────────────────────────
    lines.append("## Summary")
    lines.append("")
    lines.append("| State | Count | % of inspected |")
    lines.append("|-------|------:|---------------:|")
    for bucket in _BUCKET_ORDER:
        entries = buckets.get(bucket, [])
        # Count cap means stored != real count; label accordingly
        count_label = str(len(entries))
        if max_per_state > 0 and len(entries) >= max_per_state:
            count_label = f"{len(entries)}+"
        pct = (len(entries) / total_inspected * 100) if total_inspected else 0.0
        label = _BUCKET_LABELS.get(bucket, bucket)
        lines.append(f"| {label} | {count_label} | {pct:.1f}% |")
    lines.append(f"| **Total stored** | {total_stored} | 100% |")
    lines.append("")

    # ── By category table ────────────────────────────────────────────────────
    lines.append("## By Category")
    lines.append("")
    lines.append("| Category | Total | Indexed | DiscoveredNI | CrawledNI | 404 | Other |")
    lines.append("|----------|------:|--------:|-------------:|----------:|----:|------:|")

    # Build per-category tallies from all stored entries
    cat_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for bucket, entries in buckets.items():
        for entry in entries:
            cat = _extract_category(entry["url"])
            cat_stats[cat]["total"] += 1
            cat_stats[cat][bucket] += 1

    for cat in sorted(cat_stats):
        s = cat_stats[cat]
        lines.append(
            f"| {cat} "
            f"| {s['total']} "
            f"| {s.get('INDEXED', 0)} "
            f"| {s.get('DISCOVERED_NOT_INDEXED', 0)} "
            f"| {s.get('CRAWLED_NOT_INDEXED', 0)} "
            f"| {s.get('NOT_FOUND_404', 0)} "
            f"| {s.get('REDIRECT', 0) + s.get('BLOCKED', 0) + s.get('OTHER', 0)} |"
        )
    lines.append("")

    # ── Detail sections (ordered: 404, Discovered, Crawled, …) ───────────────
    detail_buckets = [
        ("NOT_FOUND_404", "404 URLs", "action: add 301 redirect or remove from sitemap"),
        (
            "DISCOVERED_NOT_INDEXED",
            "Discovered – Not Indexed",
            "signal: Google found links but chose not to crawl — content quality / crawl budget",
        ),
        (
            "CRAWLED_NOT_INDEXED",
            "Crawled – Not Indexed",
            "signal: Google crawled but deemed content low-quality or thin",
        ),
        ("REDIRECT", "Redirect URLs", "action: update canonical or sitemap entry"),
        ("BLOCKED", "Blocked URLs", "action: check robots.txt / server auth rules"),
        ("OTHER", "Other / Unknown States", "action: review raw coverageState values"),
    ]

    for bucket, heading, advice in detail_buckets:
        entries = buckets.get(bucket, [])
        if not entries:
            continue
        cap_note = f" (capped at {max_per_state})" if max_per_state > 0 and len(entries) >= max_per_state else ""
        lines.append(f"## {heading}{cap_note}")
        lines.append("")
        lines.append(f"_{advice}_")
        lines.append("")
        for entry in entries:
            last_crawl = entry["lastCrawlTime"] or "never crawled"
            canonical = entry["googleCanonical"]
            canonical_note = f" → canonical: {canonical}" if canonical and canonical != entry["url"] else ""
            coverage = entry["coverageState"]
            lines.append(f"- `{entry['url']}`")
            lines.append(f"  - state: {coverage} | lastCrawl: {last_crawl}{canonical_note}")
        lines.append("")

    # ── Action plan ──────────────────────────────────────────────────────────
    lines.append("## Recommended Action Plan")
    lines.append("")
    n404 = len(buckets.get("NOT_FOUND_404", []))
    n_disc = len(buckets.get("DISCOVERED_NOT_INDEXED", []))
    n_craw = len(buckets.get("CRAWLED_NOT_INDEXED", []))

    if n404:
        lines.append(f"1. **Fix {n404} 404s** — add 301 redirects to live content or remove from sitemap")
    if n_disc:
        lines.append(
            f"2. **{n_disc} Discovered-NI** — consider improving content depth/uniqueness; "
            "check internal-link equity to these pages"
        )
    if n_craw:
        lines.append(
            f"3. **{n_craw} Crawled-NI** — Google found these thin; improve content quality "
            "or consolidate with canonical redirects"
        )
    lines.append(
        "4. Re-run this audit after addressing the above "
        "(`python scripts/tools/gsc_index_audit.py --from-sitemap`)"
    )
    lines.append("")

    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--from-sitemap",
        action="store_true",
        help="Read URLs from _site/sitemap.xml (or live sitemap.xml if local missing)",
    )
    src.add_argument(
        "--urls",
        nargs="+",
        metavar="URL",
        help="Inspect a specific list of URLs instead of the sitemap",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Limit to the first N URLs (0 = no limit, default: 0)",
    )
    parser.add_argument(
        "--output",
        default="",
        metavar="PATH",
        help=(
            "Output Markdown file path. "
            "Defaults to reports/gsc-audit-YYYY-MM-DD.md"
        ),
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        metavar="SECONDS",
        help="Pause between API calls in seconds (default: 0.2)",
    )
    parser.add_argument(
        "--max-per-state",
        type=int,
        default=100,
        metavar="N",
        help=(
            "Maximum number of URL examples to save per coverage-state bucket. "
            "Use 0 for unlimited (default: 100)"
        ),
    )
    parser.add_argument(
        "--site",
        default="",
        help=(
            "GSC property URL. Defaults to GSC_SITE_URL env var or "
            f"{DEFAULT_SITE_URL}"
        ),
    )

    args = parser.parse_args(argv)

    site_url = args.site or get_env("GSC_SITE_URL", "") or DEFAULT_SITE_URL
    if not site_url.endswith("/"):
        site_url += "/"

    audit_date = datetime.now(tz=UTC).date().isoformat()
    output_path_str = args.output or f"reports/gsc-audit-{audit_date}.md"
    output_path = Path(output_path_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load URL list
    if args.from_sitemap:
        urls = _load_sitemap_urls()
    else:
        urls = list(args.urls)

    if args.limit and args.limit > 0:
        logger.info("Limiting to first %d URLs (--limit)", args.limit)
        urls = urls[: args.limit]

    if not urls:
        logger.error("No URLs to inspect — exiting")
        return 1

    logger.info(
        "Starting audit: %d URLs | site=%s | sleep=%.2fs | max-per-state=%d",
        len(urls),
        site_url,
        args.sleep,
        args.max_per_state,
    )

    service = _build_service()
    buckets = _inspect_urls(
        service=service,
        urls=urls,
        site_url=site_url,
        sleep_s=args.sleep,
        max_per_state=args.max_per_state,
    )

    # Count how many were actually inspected (sum of all stored entries,
    # accounting for the cap: we always store at least 1 per URL inspected,
    # so use total unique URLs across buckets as a proxy — for capped runs
    # the real count is args.limit or len(urls)).
    inspected_count = len(urls)

    report = _build_report(
        buckets=buckets,
        all_urls=urls,
        inspected_count=inspected_count,
        max_per_state=args.max_per_state,
        audit_date=audit_date,
    )

    output_path.write_text(report, encoding="utf-8")
    logger.info("Report saved to %s", output_path)

    # Print brief summary to stdout
    total_stored = sum(len(v) for v in buckets.values())
    sys.stdout.write(f"\nAudit complete — {inspected_count} URLs inspected\n")
    for bucket in _BUCKET_ORDER:
        entries = buckets.get(bucket, [])
        if entries:
            label = _BUCKET_LABELS.get(bucket, bucket)
            cap = "+" if args.max_per_state > 0 and len(entries) >= args.max_per_state else ""
            sys.stdout.write(f"  {label}: {len(entries)}{cap}\n")
    sys.stdout.write(f"Total stored: {total_stored}\n")
    sys.stdout.write(f"Report: {output_path}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
