#!/usr/bin/env python3

import os
import re
import sys


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "rendered_smoke")

TARGETS = [
    {
        "file": "worldmonitor_sample.html",
        "must_table": True,
        "must_details": True,
        "forbid": [r"\|\s*#\s*\|\s*이슈\s*\|", r"\|[—-]{3,}\|[—-]{3,}\|"],
    },
    {
        "file": "daily_news_sample.html",
        "must_table": True,
        "must_details": False,
        "forbid": [r"\|\s*리포트\s*\|\s*수집 건수\s*\|\s*링크\s*\|"],
    },
    {
        "file": "market_report_sample.html",
        "must_table": True,
        "must_details": False,
        "forbid": [],
    },
    {
        "file": "reference_long_link_sample.html",
        "must_table": True,
        "must_details": True,
        "forbid": [],
        "required_patterns": [r"utm_source=very_long_tracking_parameter_value_"],
    },
    {
        "file": "reference_empty_sample.html",
        "must_table": True,
        "must_details": False,
        "forbid": [r"<details"],
        "required_patterns": [r"참고 링크 없음"],
    },
    {
        "file": "reference_mixed_source_sample.html",
        "must_table": True,
        "must_details": True,
        "forbid": [],
        "required_patterns": [
            r"source-tag\">WorldMonitor/BBC World",
            r"source-tag\">WorldMonitor/Al Jazeera",
            r"source-tag\">WorldMonitor/CNBC",
        ],
    },
]

NEGATIVE_TARGETS = [
    {
        "file": "broken_table_sample.html",
        "must_table": True,
        "must_details": False,
        "forbid": [r"\|\s*#\s*\|\s*이슈\s*\|"],
        "expected_error_prefixes": ["missing-table", "forbidden-pattern"],
    },
    {
        "file": "broken_details_sample.html",
        "must_table": True,
        "must_details": True,
        "forbid": [],
        "expected_error_prefixes": ["missing-details"],
    },
]


def _validate_target(target: dict, fixture_path: str, html: str) -> list[str]:
    failures = []

    if target["must_table"] and "<table" not in html:
        failures.append(f"missing-table:{fixture_path}")

    if target["must_details"] and "<details" not in html:
        failures.append(f"missing-details:{fixture_path}")

    for pattern in target["forbid"]:
        if re.search(pattern, html):
            failures.append(f"forbidden-pattern:{pattern}:{fixture_path}")

    for pattern in target.get("required_patterns", []):
        if not re.search(pattern, html):
            failures.append(f"missing-required-pattern:{pattern}:{fixture_path}")

    return failures


def main() -> int:
    failures = []

    for target in TARGETS:
        fixture_path = os.path.join(FIXTURE_DIR, target["file"])
        if not os.path.exists(fixture_path):
            failures.append(f"missing-fixture:{fixture_path}")
            continue

        with open(fixture_path, "r", encoding="utf-8") as f:
            html = f.read()

        failures.extend(_validate_target(target, fixture_path, html))

    for target in NEGATIVE_TARGETS:
        fixture_path = os.path.join(FIXTURE_DIR, target["file"])
        if not os.path.exists(fixture_path):
            failures.append(f"missing-negative-fixture:{fixture_path}")
            continue

        with open(fixture_path, "r", encoding="utf-8") as f:
            html = f.read()

        observed = _validate_target(target, fixture_path, html)
        observed_prefixes = {entry.split(":", 1)[0] for entry in observed}
        for expected_prefix in target["expected_error_prefixes"]:
            if expected_prefix not in observed_prefixes:
                failures.append(
                    f"negative-check-missed:{expected_prefix}:{fixture_path}"
                )

    if failures:
        print("Rendered fixture smoke test failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(
        f"Rendered fixture smoke tests passed for {len(TARGETS)} positive and {len(NEGATIVE_TARGETS)} negative fixture(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
