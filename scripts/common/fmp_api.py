"""Shared Financial Modeling Prep (FMP) API helpers.

Uses the new /stable/ endpoints (post-Aug 2025 migration).
Free plan supports: single-symbol quotes.
Premium features (economic calendar, earnings, sectors, 13F) gracefully degrade
to alternative free data sources when unavailable.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List

import requests

from .config import USER_AGENT, get_env, get_ssl_verify
from .utils import request_with_retry

logger = logging.getLogger(__name__)

VERIFY_SSL = get_ssl_verify()
REQUEST_TIMEOUT = 15

_FMP_STABLE = "https://financialmodelingprep.com/stable"


def fetch_economic_calendar(days_ahead: int = 30) -> List[Dict[str, Any]]:
    """Fetch upcoming economic events.

    Tries FMP /stable/economic-calendar first, falls back to
    Forex Factory JSON (free, no key required).
    Filters to High and Medium impact events only.
    """
    api_key = get_env("FMP_API_KEY")
    start = datetime.now(UTC).strftime("%Y-%m-%d")
    end = (datetime.now(UTC) + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    # Try FMP stable endpoint first
    if api_key:
        try:
            url = f"{_FMP_STABLE}/economic-calendar"
            params = {"from": start, "to": end, "apikey": api_key}
            resp = request_with_retry(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                verify_ssl=VERIFY_SSL,
                headers={"User-Agent": USER_AGENT},
            )
            data = resp.json()
            if isinstance(data, list) and data:
                events = []
                for item in data:
                    impact = item.get("impact", "")
                    if impact not in ("High", "Medium"):
                        continue
                    events.append(
                        {
                            "event": item.get("event", ""),
                            "country": item.get("country", ""),
                            "date": item.get("date", ""),
                            "impact": impact,
                            "forecast": item.get("estimate", ""),
                            "previous": item.get("previous", ""),
                            "actual": item.get("actual", ""),
                        }
                    )
                logger.info("FMP economic calendar: fetched %d high/medium events", len(events))
                return events
        except requests.exceptions.RequestException as e:
            logger.info("FMP economic calendar unavailable: %s — trying fallback", e)

    # Fallback: Forex Factory JSON (free, no key)
    return _fetch_forex_factory_calendar()


def _fetch_forex_factory_calendar() -> List[Dict[str, Any]]:
    """Fallback: fetch economic calendar from Forex Factory JSON feed."""
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        resp = request_with_retry(
            url,
            timeout=REQUEST_TIMEOUT,
            verify_ssl=VERIFY_SSL,
            headers={"User-Agent": USER_AGENT},
        )
        data = resp.json()
        if not isinstance(data, list):
            return []

        events = []
        for item in data:
            impact = item.get("impact", "")
            if impact not in ("High", "Medium"):
                continue
            events.append(
                {
                    "event": item.get("title", ""),
                    "country": item.get("country", ""),
                    "date": item.get("date", ""),
                    "impact": impact,
                    "forecast": item.get("forecast", ""),
                    "previous": item.get("previous", ""),
                    "actual": item.get("actual", ""),
                }
            )
        logger.info("Forex Factory calendar: fetched %d high/medium events", len(events))
        return events
    except requests.exceptions.RequestException as e:
        logger.warning("Forex Factory calendar fetch failed: %s", e)
        return []


def fetch_earnings_calendar(days_ahead: int = 7) -> List[Dict[str, Any]]:
    """Fetch upcoming earnings.

    Tries FMP first, falls back to Nasdaq RSS for earnings news.
    """
    api_key = get_env("FMP_API_KEY")
    start = datetime.now(UTC).strftime("%Y-%m-%d")
    end = (datetime.now(UTC) + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    if api_key:
        try:
            url = f"{_FMP_STABLE}/earning-calendar"
            params = {"from": start, "to": end, "apikey": api_key}
            resp = request_with_retry(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                verify_ssl=VERIFY_SSL,
                headers={"User-Agent": USER_AGENT},
            )
            data = resp.json()
            if isinstance(data, list) and data:
                earnings = []
                for item in data:
                    market_cap = item.get("marketCap", 0) or 0
                    try:
                        market_cap = float(market_cap)
                    except (ValueError, TypeError):
                        market_cap = 0
                    if market_cap < 2_000_000_000:
                        continue
                    earnings.append(
                        {
                            "symbol": item.get("symbol", ""),
                            "date": item.get("date", ""),
                            "eps_estimated": item.get("epsEstimated", ""),
                            "revenue_estimated": item.get("revenueEstimated", ""),
                            "time": item.get("time", ""),
                        }
                    )
                logger.info("FMP earnings calendar: fetched %d large-cap earnings", len(earnings))
                return earnings
        except requests.exceptions.RequestException as e:
            logger.info("FMP earnings calendar unavailable: %s — trying fallback", e)

    # Fallback: Google News RSS for earnings announcements
    return _fetch_earnings_news_fallback()


def _fetch_earnings_news_fallback() -> List[Dict[str, Any]]:
    """Fallback: fetch earnings news headlines from Google News RSS."""
    from .rss_fetcher import fetch_rss_feed

    items = fetch_rss_feed(
        url="https://news.google.com/rss/search?q=%22earnings+report%22+OR+%22quarterly+results%22+%22beat+estimates%22&hl=en-US&gl=US&ceid=US:en",
        source_name="Earnings News",
        tags=["earnings"],
        limit=20,
        max_age_hours=168,  # 7 days
    )
    earnings = []
    for item in items:
        earnings.append(
            {
                "symbol": "",
                "date": item.get("published", ""),
                "eps_estimated": "",
                "revenue_estimated": "",
                "time": "",
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "is_news_fallback": True,
            }
        )
    logger.info("Earnings news fallback: fetched %d items", len(earnings))
    return earnings


def fetch_institutional_flows(symbol: str) -> List[Dict[str, Any]]:
    """Fetch 13F institutional holders for a given symbol.

    Returns list of top holders with change info.
    Only available with FMP premium plan.
    """
    api_key = get_env("FMP_API_KEY")
    if not api_key:
        logger.info("FMP_API_KEY not set, skipping institutional flows fetch")
        return []

    try:
        url = f"{_FMP_STABLE}/institutional-holder"
        params = {"symbol": symbol, "apikey": api_key}
        resp = request_with_retry(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            verify_ssl=VERIFY_SSL,
            headers={"User-Agent": USER_AGENT},
        )
        data = resp.json()
        if not isinstance(data, list):
            logger.warning("FMP institutional holders for %s: unexpected format", symbol)
            return []

        holders = []
        for item in data:
            holders.append(
                {
                    "holder": item.get("holder", ""),
                    "shares": item.get("shares", 0),
                    "date_reported": item.get("dateReported", ""),
                    "change": item.get("change", 0),
                    "change_pct": item.get("changeInSharesNumberPercentage", 0),
                }
            )
        logger.info("FMP institutional holders for %s: fetched %d holders", symbol, len(holders))
        return holders
    except requests.exceptions.RequestException as e:
        logger.warning("FMP institutional flows fetch failed for %s: %s", symbol, e)
        return []


def fetch_market_index_data(symbol: str) -> Dict[str, Any]:
    """Fetch market index/stock quote from FMP /stable/quote.

    Works on free plan for individual symbols: SPY, AAPL, ^GSPC, ^VIX, etc.
    """
    api_key = get_env("FMP_API_KEY")
    if not api_key:
        logger.info("FMP_API_KEY not set, skipping market index fetch for %s", symbol)
        return {}

    try:
        url = f"{_FMP_STABLE}/quote"
        params = {"symbol": symbol, "apikey": api_key}
        resp = request_with_retry(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            verify_ssl=VERIFY_SSL,
            headers={"User-Agent": USER_AGENT},
        )
        data = resp.json()
        if isinstance(data, str) and "Restricted" in data:
            logger.info("FMP quote for %s: restricted on free plan", symbol)
            return {}
        if not isinstance(data, list) or not data:
            logger.warning("FMP quote for %s: empty or unexpected format", symbol)
            return {}

        quote = data[0]
        logger.info("FMP quote: fetched %s @ %s", symbol, quote.get("price"))
        return {
            "symbol": quote.get("symbol", symbol),
            "name": quote.get("name", symbol),
            "price": quote.get("price", 0),
            "change": quote.get("change", 0),
            "change_pct": quote.get("changePercentage", 0),
            "day_high": quote.get("dayHigh", 0),
            "day_low": quote.get("dayLow", 0),
            "volume": quote.get("volume", 0),
            "year_high": quote.get("yearHigh", 0),
            "year_low": quote.get("yearLow", 0),
            "market_cap": quote.get("marketCap", 0),
            "avg50": quote.get("priceAvg50", 0),
            "avg200": quote.get("priceAvg200", 0),
        }
    except requests.exceptions.RequestException as e:
        logger.warning("FMP market index fetch failed for %s: %s", symbol, e)
        return {}


def fetch_sector_performance() -> List[Dict[str, Any]]:
    """Fetch sector performance.

    Tries FMP first, falls back to yfinance sector ETFs.
    """
    api_key = get_env("FMP_API_KEY")

    if api_key:
        try:
            url = f"{_FMP_STABLE}/sectors-performance"
            params = {"apikey": api_key}
            resp = request_with_retry(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                verify_ssl=VERIFY_SSL,
                headers={"User-Agent": USER_AGENT},
            )
            data = resp.json()
            if isinstance(data, list) and data:
                sectors = []
                for item in data:
                    sectors.append(
                        {
                            "sector": item.get("sector", ""),
                            "change_pct": item.get("changesPercentage", ""),
                        }
                    )

                def _parse_change(s: Dict[str, Any]) -> float:
                    try:
                        return float(str(s.get("change_pct", "0")).replace("%", ""))
                    except (ValueError, TypeError):
                        return 0.0

                sectors.sort(key=_parse_change, reverse=True)
                logger.info("FMP sector performance: fetched %d sectors", len(sectors))
                return sectors
        except requests.exceptions.RequestException as e:
            logger.info("FMP sector performance unavailable: %s — trying fallback", e)

    # Fallback: yfinance sector ETFs
    return _fetch_sector_etf_fallback()


def _fetch_sector_etf_fallback() -> List[Dict[str, Any]]:
    """Fallback: compute sector performance from sector ETFs via yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        logger.info("yfinance not installed, skipping sector ETF fallback")
        return []

    etf_map = {
        "XLK": "Technology",
        "XLV": "Healthcare",
        "XLF": "Financial Services",
        "XLY": "Consumer Cyclical",
        "XLC": "Communication Services",
        "XLI": "Industrials",
        "XLP": "Consumer Defensive",
        "XLE": "Energy",
        "XLRE": "Real Estate",
        "XLB": "Basic Materials",
        "XLU": "Utilities",
    }
    sectors = []
    for symbol, sector in etf_map.items():
        try:
            info = yf.Ticker(symbol).fast_info
            price = getattr(info, "last_price", None)
            prev = getattr(info, "previous_close", None)
            if price and prev:
                change_pct = ((price - prev) / prev) * 100
                sectors.append({"sector": sector, "change_pct": f"{change_pct:.2f}%"})
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning("yfinance %s: %s", symbol, e)

    sectors.sort(key=lambda s: float(str(s.get("change_pct", "0")).replace("%", "")), reverse=True)
    logger.info("Sector ETF fallback: fetched %d sectors", len(sectors))
    return sectors


def fetch_treasury_rates() -> List[Dict[str, Any]]:
    """Fetch US Treasury rates (2Y, 5Y, 10Y, 30Y).

    Tries FMP /stable/treasury-rates first (requires FMP_API_KEY),
    falls back to yfinance symbols: ^IRX (13W), ^FVX (5Y), ^TNX (10Y), ^TYX (30Y).
    Returns list of dicts with keys: maturity, rate, change, change_pct.
    """
    api_key = get_env("FMP_API_KEY")

    if api_key:
        try:
            url = f"{_FMP_STABLE}/treasury-rates"
            params = {"apikey": api_key}
            resp = request_with_retry(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                verify_ssl=VERIFY_SSL,
                headers={"User-Agent": USER_AGENT},
            )
            data = resp.json()
            if isinstance(data, list) and data:
                # FMP returns list of objects; take the most recent entry
                latest = data[0]
                rates = []
                maturity_map = {
                    "month3": "3개월",
                    "year2": "2년",
                    "year5": "5년",
                    "year10": "10년",
                    "year30": "30년",
                }
                for key, label in maturity_map.items():
                    val = latest.get(key)
                    if val is not None:
                        try:
                            rate_f = float(val)
                        except (ValueError, TypeError):
                            continue
                        rates.append(
                            {
                                "maturity": label,
                                "rate": rate_f,
                                "change": None,
                                "change_pct": None,
                            }
                        )
                logger.info("FMP treasury rates: fetched %d maturities", len(rates))
                return rates
        except requests.exceptions.RequestException as e:
            logger.info("FMP treasury rates unavailable: %s — trying yfinance fallback", e)

    # Fallback: yfinance treasury symbols
    return _fetch_treasury_yfinance_fallback()


def _fetch_treasury_yfinance_fallback() -> List[Dict[str, Any]]:
    """Fallback: fetch Treasury yields via yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        logger.info("yfinance not installed, skipping treasury fallback")
        return []

    # yfinance symbols → maturity label
    symbol_map = {
        "^IRX": "3개월",
        "^FVX": "5년",
        "^TNX": "10년",
        "^TYX": "30년",
    }
    rates = []
    for symbol, label in symbol_map.items():
        try:
            info = yf.Ticker(symbol).fast_info
            price = getattr(info, "last_price", None)
            prev = getattr(info, "previous_close", None)
            if price is None:
                continue
            change = (price - prev) if prev else None
            change_pct = ((price - prev) / prev * 100) if prev else None
            rates.append(
                {
                    "maturity": label,
                    "rate": float(price),
                    "change": round(change, 4) if change is not None else None,
                    "change_pct": round(change_pct, 4) if change_pct is not None else None,
                }
            )
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning("yfinance treasury %s: %s", symbol, e)

    # Sort by maturity order
    order = {"3개월": 0, "2년": 1, "5년": 2, "10년": 3, "30년": 4}
    rates.sort(key=lambda r: order.get(r["maturity"], 99))
    logger.info("yfinance treasury fallback: fetched %d rates", len(rates))
    return rates


def fetch_ipo_calendar(days_ahead: int = 30) -> List[Dict[str, Any]]:
    """Fetch upcoming IPO calendar.

    Tries FMP /stable/ipo-calendar first (requires FMP_API_KEY),
    falls back to Google News RSS for IPO news.
    Returns list of dicts with keys: date, company, symbol, exchange,
    shares_offered, price_range, market_value.
    """
    api_key = get_env("FMP_API_KEY")
    start = datetime.now(UTC).strftime("%Y-%m-%d")
    end = (datetime.now(UTC) + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    if api_key:
        try:
            url = f"{_FMP_STABLE}/ipo-calendar"
            params = {"from": start, "to": end, "apikey": api_key}
            resp = request_with_retry(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                verify_ssl=VERIFY_SSL,
                headers={"User-Agent": USER_AGENT},
            )
            data = resp.json()
            if isinstance(data, list) and data:
                ipos = []
                for item in data:
                    ipos.append(
                        {
                            "date": item.get("date", ""),
                            "company": item.get("company", ""),
                            "symbol": item.get("symbol", ""),
                            "exchange": item.get("exchange", ""),
                            "shares_offered": item.get("shares", ""),
                            "price_range": item.get("priceRange", ""),
                            "market_value": item.get("marketCap", ""),
                            "is_news_fallback": False,
                        }
                    )
                ipos.sort(key=lambda x: x.get("date", ""))
                logger.info("FMP IPO calendar: fetched %d upcoming IPOs", len(ipos))
                return ipos
        except requests.exceptions.RequestException as e:
            logger.info("FMP IPO calendar unavailable: %s — trying fallback", e)

    # Fallback: Google News RSS
    return _fetch_ipo_news_fallback()


def _fetch_ipo_news_fallback() -> List[Dict[str, Any]]:
    """Fallback: fetch IPO news headlines from Google News RSS."""
    from .rss_fetcher import fetch_rss_feed

    items = fetch_rss_feed(
        url="https://news.google.com/rss/search?q=IPO+%22initial+public+offering%22+2026&hl=en-US&gl=US&ceid=US:en",
        source_name="IPO News",
        tags=["ipo"],
        limit=15,
        max_age_hours=168,  # 7 days
    )
    ipos = []
    for item in items:
        ipos.append(
            {
                "date": item.get("published", ""),
                "company": "",
                "symbol": "",
                "exchange": "",
                "shares_offered": "",
                "price_range": "",
                "market_value": "",
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "is_news_fallback": True,
            }
        )
    logger.info("IPO news fallback: fetched %d items", len(ipos))
    return ipos
