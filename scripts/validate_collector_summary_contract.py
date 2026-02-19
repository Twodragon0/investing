#!/usr/bin/env python3

import ast
from pathlib import Path
from typing import List


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"

TARGET_COLLECTORS = [
    "collect_crypto_news.py",
    "collect_stock_news.py",
    "collect_social_media.py",
    "collect_regulatory.py",
    "collect_political_trades.py",
    "collect_worldmonitor_news.py",
    "collect_coinmarketcap.py",
]

REQUIRED_KWARGS = {
    "collector",
    "source_count",
    "unique_items",
    "post_created",
    "started_at",
}


def _find_calls(tree: ast.AST) -> List[ast.Call]:
    calls: List[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == "log_collection_summary":
                calls.append(node)
            elif isinstance(fn, ast.Attribute) and fn.attr == "log_collection_summary":
                calls.append(node)
    return calls


def _validate_file(path: Path) -> List[str]:
    errors: List[str] = []
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    calls = _find_calls(tree)

    if not calls:
        errors.append(f"missing-call:{path}")
        return errors

    valid_call = False
    for call in calls:
        kwargs = {kw.arg for kw in call.keywords if kw.arg}
        if REQUIRED_KWARGS.issubset(kwargs):
            valid_call = True
            break

    if not valid_call:
        errors.append(f"missing-required-kwargs:{path}")

    return errors


def main() -> int:
    failures: List[str] = []

    for rel in TARGET_COLLECTORS:
        file_path = SCRIPTS_DIR / rel
        if not file_path.exists():
            failures.append(f"missing-file:{file_path}")
            continue
        failures.extend(_validate_file(file_path))

    if failures:
        print("Collector summary contract failures:")
        for fail in failures:
            print(f"- {fail}")
        return 1

    print(
        f"Collector summary contract passed for {len(TARGET_COLLECTORS)} collector(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
