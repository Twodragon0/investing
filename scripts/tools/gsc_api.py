#!/usr/bin/env python3
"""Google Search Console API CLI.

Query Search Console programmatically: sitemap status, URL inspection,
search analytics, and sitemap re-submission.

Setup (one-time)
----------------
1. Google Cloud Console:
   - Create or pick a project at https://console.cloud.google.com/
   - Enable both APIs:
     * "Search Console API"
     * "Web Search Indexing API" (only if you also need indexing-API push)
2. Service account:
   - IAM & Admin → Service Accounts → Create Service Account
   - Grant role: none required at the GCP level
   - Keys → Add Key → JSON. Save the file somewhere outside the repo.
3. Search Console (https://search.google.com/search-console):
   - Settings → Users and permissions → Add user
   - Email = the service account's email (foo@bar.iam.gserviceaccount.com)
   - Permission: "Owner" (URL inspection requires Owner)
4. Environment:
   - GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   - GSC_SITE_URL=https://investing.2twodragon.com/   # trailing slash matters

Usage
-----
  python scripts/tools/gsc_api.py sitemap-status
  python scripts/tools/gsc_api.py inspect https://investing.2twodragon.com/
  python scripts/tools/gsc_api.py analytics --days 7 --row-limit 25
  python scripts/tools/gsc_api.py submit-sitemap https://investing.2twodragon.com/sitemap.xml

Dependencies (install once into your venv)
------------------------------------------
  pip install google-api-python-client google-auth

This script never modifies disk state. Only `submit-sitemap` mutates
external state (tells GSC to re-fetch the sitemap), so it is the only
sub-command that requires explicit confirmation by default.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Use shared helpers per scripts/AGENTS.md guardrails. Import config.py
# directly to avoid triggering common/__init__.py's heavy collector imports
# (requests, lxml, etc.) which the GSC workflow does not install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from config import get_env, setup_logging  # noqa: E402

logger = setup_logging("gsc_api")

DEFAULT_SITE_URL = "https://investing.2twodragon.com/"


def _require_googleapi() -> tuple[Any, Any]:
    """Import google-api-python-client lazily with a clear error on failure."""
    try:
        from google.oauth2 import service_account  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:
        logger.error(
            "missing dependency. Install with: pip install google-api-python-client google-auth (%s)",
            exc,
        )
        sys.exit(2)
    return service_account, build


def _build_service():
    """Authenticate with the service account and return the GSC client."""
    cred_path = get_env("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not cred_path:
        logger.error(
            "GOOGLE_APPLICATION_CREDENTIALS env var is not set. Point it at your service-account JSON file path."
        )
        sys.exit(2)
    if not os.path.isfile(cred_path):
        logger.error("credentials file not found: %s", cred_path)
        sys.exit(2)

    service_account, build = _require_googleapi()
    creds = service_account.Credentials.from_service_account_file(
        cred_path,
        scopes=["https://www.googleapis.com/auth/webmasters"],
    )
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def _site_url(args: argparse.Namespace) -> str:
    site = args.site or get_env("GSC_SITE_URL", "") or DEFAULT_SITE_URL
    if not site.endswith("/"):
        site += "/"
    return site


def _emit(line: str = "") -> None:
    """Write a line of structured CLI output to stdout (pipe-friendly)."""
    sys.stdout.write(line + "\n")


def cmd_sitemap_status(args: argparse.Namespace) -> int:
    """List every sitemap registered for the property and its last-fetched status."""
    service = _build_service()
    site = _site_url(args)
    resp = service.sitemaps().list(siteUrl=site).execute()
    sitemaps = resp.get("sitemap", [])
    if not sitemaps:
        _emit(f"No sitemaps registered for {site}")
        return 0
    for s in sitemaps:
        _emit(f"- path:        {s.get('path')}")
        _emit(f"  type:        {s.get('type', '(unknown)')}")
        _emit(f"  lastSubmitted: {s.get('lastSubmitted', '(none)')}")
        _emit(f"  isPending:   {s.get('isPending')}")
        _emit(f"  errors:      {s.get('errors')}")
        _emit(f"  warnings:    {s.get('warnings')}")
        for c in s.get("contents", []) or []:
            _emit(f"    - {c.get('type')}: submitted={c.get('submitted')} indexed={c.get('indexed')}")
        _emit()
    return 0


def cmd_submit_sitemap(args: argparse.Namespace) -> int:
    """Tell GSC to re-fetch a sitemap. External-state change."""
    if not args.confirm:
        logger.error(
            "submit-sitemap mutates external state (re-queues the sitemap fetch in GSC). "
            "Re-run with --confirm to proceed."
        )
        return 1
    service = _build_service()
    site = _site_url(args)
    feedpath = args.feedpath
    service.sitemaps().submit(siteUrl=site, feedpath=feedpath).execute()
    _emit(f"Submitted: {feedpath} for property {site}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    """Run the URL Inspection API on a single URL and emit the verdict."""
    service = _build_service()
    site = _site_url(args)
    body = {
        "inspectionUrl": args.url,
        "siteUrl": site,
        "languageCode": "ko-KR",
    }
    resp = service.urlInspection().index().inspect(body=body).execute()
    _emit(json.dumps(resp, indent=2, ensure_ascii=False))
    return 0


def cmd_analytics(args: argparse.Namespace) -> int:
    """Top queries / pages from the search analytics API over the last N days."""
    service = _build_service()
    site = _site_url(args)
    end = datetime.now(tz=UTC).date()
    start = end - timedelta(days=args.days)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": [args.dimension],
        "rowLimit": args.row_limit,
    }
    resp = service.searchanalytics().query(siteUrl=site, body=body).execute()
    rows = resp.get("rows", [])
    if not rows:
        _emit(f"No data for {start} to {end}.")
        return 0
    _emit(f"Top {len(rows)} {args.dimension}s ({start} → {end}):")
    _emit(f"{'#':>3}  {'clicks':>7}  {'impr':>7}  {'ctr':>5}  {'pos':>5}  key")
    for i, row in enumerate(rows, 1):
        keys = " | ".join(row.get("keys", []))
        clicks = row.get("clicks", 0)
        impr = row.get("impressions", 0)
        ctr = row.get("ctr", 0.0)
        pos = row.get("position", 0.0)
        _emit(f"{i:>3}  {clicks:>7}  {impr:>7}  {ctr:>5.2%}  {pos:>5.1f}  {keys}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--site",
        help=(
            "GSC property URL (e.g. https://investing.2twodragon.com/). "
            "Defaults to GSC_SITE_URL env var or the project default."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sitemap-status", help="List sitemaps and their fetch status").set_defaults(func=cmd_sitemap_status)

    p_inspect = sub.add_parser("inspect", help="URL Inspection API on a single URL")
    p_inspect.add_argument("url")
    p_inspect.set_defaults(func=cmd_inspect)

    p_analytics = sub.add_parser("analytics", help="Top queries/pages from Search Analytics")
    p_analytics.add_argument("--days", type=int, default=7)
    p_analytics.add_argument(
        "--dimension",
        default="query",
        choices=["query", "page", "country", "device", "searchAppearance"],
    )
    p_analytics.add_argument("--row-limit", type=int, default=25)
    p_analytics.set_defaults(func=cmd_analytics)

    p_submit = sub.add_parser("submit-sitemap", help="Re-submit a sitemap to GSC (external state change)")
    p_submit.add_argument("feedpath", help="Full sitemap URL")
    p_submit.add_argument(
        "--confirm",
        action="store_true",
        help="Required: confirms you want to mutate GSC state",
    )
    p_submit.set_defaults(func=cmd_submit_sitemap)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
