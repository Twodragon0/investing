"""Backfill null btc_price entries in _state/signal_history.json.

Fetches historical BTC-USD daily close from CoinGecko free history endpoint,
with fallback to Blockchain.com chart API and yfinance.

Usage:
    python scripts/backfill_signal_history_btc_price.py          # dry-run (default)
    python scripts/backfill_signal_history_btc_price.py --apply  # write changes
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional

# Allow running from repo root or scripts/ directory
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_SCRIPTS_DIR, ".."))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from common.config import setup_logging  # noqa: E402
from common.utils import request_with_retry  # noqa: E402

logger = setup_logging("backfill_signal_history")

_HISTORY_FILE = os.path.join(_REPO_ROOT, "_state", "signal_history.json")
_NOW_UTC = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Price fetchers ────────────────────────────────────────────────────────────


def _fetch_coingecko(date_str: str) -> Optional[float]:
    """Fetch BTC-USD historical close from CoinGecko free API.

    Args:
        date_str: YYYY-MM-DD format date.

    Returns:
        BTC price in USD or None on failure.
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    cg_date = dt.strftime("%d-%m-%Y")
    url = f"https://api.coingecko.com/api/v3/coins/bitcoin/history?date={cg_date}&localization=false"
    try:
        resp = request_with_retry(url, timeout=15, max_retries=1)
        data = resp.json()
        price = data.get("market_data", {}).get("current_price", {}).get("usd")
        if price is not None:
            logger.info("CoinGecko: %s → $%.2f", date_str, price)
            return float(price)
        logger.warning("CoinGecko: no price in response for %s", date_str)
        return None
    except Exception as e:
        logger.warning("CoinGecko fetch failed for %s: %s", date_str, e)
        return None


def _fetch_blockchain_com(date_str: str) -> Optional[float]:
    """Fallback: Blockchain.com chart API (market-price, daily).

    Args:
        date_str: YYYY-MM-DD format date.

    Returns:
        BTC price in USD or None on failure.
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    # Use a window starting one day before the target date to ensure we get the day's data
    start_ts = int((dt - timedelta(days=1)).timestamp())
    url = "https://api.blockchain.info/charts/market-price"
    params = {
        "timespan": "3days",
        "start": start_ts,
        "format": "json",
        "sampled": "true",
    }
    try:
        resp = request_with_retry(url, params=params, timeout=15, max_retries=1)
        data = resp.json()
        values = data.get("values", [])
        if not values:
            logger.warning("Blockchain.com: no values for %s", date_str)
            return None
        target_date = dt.strftime("%Y-%m-%d")
        # Find the closest entry to target date
        for v in values:
            entry_dt = datetime.fromtimestamp(v["x"], tz=UTC)
            if entry_dt.strftime("%Y-%m-%d") == target_date:
                price = float(v["y"])
                logger.info("Blockchain.com: %s → $%.2f", date_str, price)
                return price
        # Fall back to last value in range
        price = float(values[-1]["y"])
        logger.warning("Blockchain.com: exact date not found, using nearest: $%.2f", price)
        return price
    except Exception as e:
        logger.warning("Blockchain.com fetch failed for %s: %s", date_str, e)
        return None


def _fetch_yfinance(date_str: str) -> Optional[float]:
    """Fallback: yfinance historical OHLCV (Close price).

    Args:
        date_str: YYYY-MM-DD format date.

    Returns:
        BTC-USD close price or None on failure.
    """
    try:
        import yfinance as yf  # type: ignore[import]

        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        end = (dt + timedelta(days=2)).strftime("%Y-%m-%d")
        ticker = yf.Ticker("BTC-USD")
        hist = ticker.history(start=date_str, end=end)
        if hist.empty:
            logger.warning("yfinance: empty result for %s", date_str)
            return None
        price = float(hist["Close"].iloc[0])
        logger.info("yfinance: %s → $%.2f", date_str, price)
        return price
    except Exception as e:
        logger.warning("yfinance fetch failed for %s: %s", date_str, e)
        return None


def fetch_btc_price(date_str: str) -> tuple[Optional[float], str]:
    """Fetch BTC-USD price using provider chain: CoinGecko → Blockchain.com → yfinance.

    Args:
        date_str: YYYY-MM-DD format date.

    Returns:
        (price, provider_name) tuple. price is None if all providers failed.
    """
    price = _fetch_coingecko(date_str)
    if price is not None:
        return price, "CoinGecko"

    price = _fetch_blockchain_com(date_str)
    if price is not None:
        return price, "Blockchain.com"

    price = _fetch_yfinance(date_str)
    if price is not None:
        return price, "yfinance"

    return None, "none"


# ── Accuracy helpers (mirrors signal_tracker logic) ───────────────────────────


def _verdict_to_direction(verdict: str) -> Optional[str]:
    """Convert verdict to expected direction. Returns None for 혼조/중립."""
    if verdict == "강세":
        return "상승"
    if verdict == "약세":
        return "하락"
    return None


def _price_direction(change_pct: float) -> str:
    """Convert price change % to direction label."""
    if change_pct > 1.0:
        return "상승"
    if change_pct < -1.0:
        return "하락"
    return "보합"


def _compute_accuracy_block(
    prev_entry: Dict[str, Any],
    today_btc_price: float,
) -> Dict[str, Any]:
    """Compute accuracy block for prev_entry given today's btc_price.

    Args:
        prev_entry: The history entry for the previous day.
        today_btc_price: Today's BTC price used to compute change.

    Returns:
        accuracy dict matching signal_tracker schema.
    """
    prev_btc = prev_entry["btc_price"]
    change_pct = ((today_btc_price - prev_btc) / prev_btc) * 100
    actual_dir = _price_direction(change_pct)
    predicted_verdict = prev_entry.get("verdict", "")
    predicted_direction = _verdict_to_direction(predicted_verdict)
    correct: Optional[bool] = None
    if predicted_direction is not None:
        correct = predicted_direction == actual_dir

    return {
        "predicted_verdict": predicted_verdict,
        "predicted_score": prev_entry.get("composite_score", 0.0),
        "actual_price_change_pct": round(change_pct, 4),
        "actual_direction": actual_dir,
        "correct": correct,
        "evaluated_at": _NOW_UTC,
    }


# ── Main backfill logic ───────────────────────────────────────────────────────


def load_history(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_history(path: str, entries: List[Dict[str, Any]]) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def backfill(dry_run: bool = True) -> None:
    """Main backfill routine.

    Args:
        dry_run: If True, print planned changes without writing. Default True.
    """
    entries = load_history(_HISTORY_FILE)
    # Build index: date -> position
    date_index: Dict[str, int] = {e["date"]: i for i, e in enumerate(entries)}

    null_entries = [e for e in entries if e.get("btc_price") is None]
    if not null_entries:
        logger.info("No null btc_price entries found. Nothing to backfill.")
        print("No null btc_price entries found. Nothing to backfill.")
        return

    print(f"Found {len(null_entries)} null btc_price entries: {[e['date'] for e in null_entries]}")
    print()

    changes: List[Dict[str, Any]] = []

    for entry in null_entries:
        date_str = entry["date"]
        price, provider = fetch_btc_price(date_str)

        if price is None:
            print(f"  SKIP {date_str}: all providers failed, btc_price stays null")
            changes.append({"date": date_str, "btc_price": None, "provider": "none", "predecessor_accuracy": False})
            continue

        # Plan: set btc_price + backfilled_at on this entry
        entry_change = {
            "date": date_str,
            "btc_price": price,
            "provider": provider,
            "predecessor_accuracy": False,
        }

        # Check if previous calendar day exists and needs accuracy block
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        prev_date_str = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
        prev_idx = date_index.get(prev_date_str)

        if prev_idx is not None:
            prev_entry = entries[prev_idx]
            prev_btc = prev_entry.get("btc_price")
            if prev_btc is not None and prev_btc > 0:
                acc = _compute_accuracy_block(prev_entry, price)
                entry_change["predecessor_accuracy"] = True
                entry_change["predecessor_date"] = prev_date_str
                entry_change["predecessor_accuracy_block"] = acc
                print(
                    f"  BACKFILL {date_str}: price=${price:,.2f} (via {provider}) | "
                    f"predecessor {prev_date_str} accuracy: "
                    f"{acc['actual_direction']} ({acc['actual_price_change_pct']:+.4f}%) "
                    f"correct={acc['correct']}"
                )
            else:
                print(
                    f"  BACKFILL {date_str}: price=${price:,.2f} (via {provider}) | "
                    f"predecessor {prev_date_str} has no btc_price, skip accuracy"
                )
        else:
            print(
                f"  BACKFILL {date_str}: price=${price:,.2f} (via {provider}) | "
                f"no predecessor entry for {prev_date_str}"
            )

        changes.append(entry_change)

    print()

    if dry_run:
        print("DRY-RUN: no changes written. Re-run with --apply to write.")
        return

    # Apply changes
    applied = 0
    for change in changes:
        if change["btc_price"] is None:
            continue
        idx = date_index[change["date"]]
        entries[idx]["btc_price"] = change["btc_price"]
        entries[idx]["backfilled_at"] = _NOW_UTC

        if change.get("predecessor_accuracy") and "predecessor_date" in change:
            prev_idx = date_index[change["predecessor_date"]]
            entries[prev_idx]["accuracy"] = change["predecessor_accuracy_block"]
            entries[prev_idx]["accuracy"]["backfilled_at"] = _NOW_UTC

        applied += 1

    save_history(_HISTORY_FILE, entries)
    print(f"APPLIED: {applied} entries backfilled, file written atomically.")

    # Final validation: count remaining nulls
    remaining_nulls = [e["date"] for e in entries if e.get("btc_price") is None]
    if remaining_nulls:
        print(f"WARNING: {len(remaining_nulls)} null btc_price entries remain: {remaining_nulls}")
    else:
        print("VALIDATION: 0 null btc_price entries remain.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill null btc_price entries in signal_history.json")
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually write changes (default: dry-run mode)",
    )
    args = parser.parse_args()
    dry_run = not args.apply
    if dry_run:
        print("Mode: DRY-RUN (pass --apply to write changes)\n")
    else:
        print("Mode: APPLY\n")
    backfill(dry_run=dry_run)


if __name__ == "__main__":
    main()
