"""Entity extraction and relationship mapping for news items.

Inspired by MiroFish's ontology_generator.py pattern.
Extracts entities (companies, people, crypto, indices) from news titles
and maps relationships between them for news grouping.
"""

from collections import defaultdict
from typing import Any

# Major entities to track
_CRYPTO_ENTITIES = {
    "bitcoin": ["BTC", "비트코인", "Bitcoin"],
    "ethereum": ["ETH", "이더리움", "Ethereum"],
    "xrp": ["XRP", "리플", "Ripple"],
    "solana": ["SOL", "솔라나", "Solana"],
    "dogecoin": ["DOGE", "도지코인", "Dogecoin"],
    "cardano": ["ADA", "카르다노", "Cardano"],
    "bnb": ["BNB", "바이낸스코인"],
    "avalanche": ["AVAX", "아발란체"],
    "polygon": ["MATIC", "POL", "폴리곤"],
    "chainlink": ["LINK", "체인링크"],
}

_STOCK_ENTITIES = {
    "apple": ["AAPL", "애플", "Apple"],
    "nvidia": ["NVDA", "엔비디아", "Nvidia", "NVIDIA"],
    "tesla": ["TSLA", "테슬라", "Tesla"],
    "microsoft": ["MSFT", "마이크로소프트", "Microsoft"],
    "amazon": ["AMZN", "아마존", "Amazon"],
    "google": ["GOOG", "GOOGL", "구글", "Google", "Alphabet"],
    "meta": ["META", "메타", "Meta", "Facebook"],
    "samsung": ["삼성", "삼성전자", "Samsung"],
    "sk_hynix": ["SK하이닉스", "SK Hynix"],
}

_INDEX_ENTITIES = {
    "sp500": ["S&P 500", "S&P500", "SPY", "SPX"],
    "nasdaq": ["나스닥", "NASDAQ", "QQQ", "Nasdaq"],
    "dow": ["다우", "Dow", "DIA", "DJIA"],
    "kospi": ["코스피", "KOSPI"],
    "kosdaq": ["코스닥", "KOSDAQ"],
    "nikkei": ["니케이", "Nikkei", "日経"],
    "vix": ["VIX", "공포지수", "변동성지수"],
}

_PERSON_ENTITIES = {
    "trump": ["트럼프", "Trump"],
    "powell": ["파월", "Powell", "Fed Chair"],
    "yellen": ["옐런", "Yellen"],
    "gensler": ["겐슬러", "Gensler", "SEC Chair"],
    "musk": ["머스크", "Musk", "Elon"],
    "buffett": ["버핏", "Buffett", "Berkshire"],
}

_ORG_ENTITIES = {
    "fed": ["연준", "Fed", "Federal Reserve", "FOMC"],
    "sec": ["SEC", "증권거래위원회"],
    "ecb": ["ECB", "유럽중앙은행"],
    "boj": ["BOJ", "일본은행"],
    "bok": ["한국은행", "BOK", "한은"],
    "binance": ["바이낸스", "Binance"],
    "coinbase": ["코인베이스", "Coinbase"],
}

_THEME_KEYWORDS = {
    "금리": ["금리", "이자율", "기준금리", "rate", "interest rate", "rate cut", "rate hike"],
    "인플레이션": ["인플레", "CPI", "물가", "inflation"],
    "ETF": ["ETF", "상장지수펀드"],
    "규제": ["규제", "regulation", "regulatory", "법안", "bill"],
    "해킹": ["해킹", "hack", "exploit", "breach", "취약점"],
    "IPO": ["IPO", "상장", "공모"],
    "실적": ["실적", "earnings", "revenue", "매출", "분기"],
    "무역전쟁": ["관세", "tariff", "무역", "trade war", "sanctions", "제재"],
    "AI": ["AI", "인공지능", "artificial intelligence", "GPT", "LLM"],
    "반도체": ["반도체", "semiconductor", "chip", "칩"],
}


def extract_entities(text: str) -> dict[str, list[str]]:
    """Extract named entities from text.

    Returns dict with keys: crypto, stock, index, person, org, theme
    Each value is a list of canonical entity names found.
    """
    results: dict[str, list[str]] = {
        "crypto": [],
        "stock": [],
        "index": [],
        "person": [],
        "org": [],
        "theme": [],
    }

    text_upper = text.upper()
    text_lower = text.lower()

    for canonical, aliases in _CRYPTO_ENTITIES.items():
        for alias in aliases:
            if alias in text or alias.upper() in text_upper:
                if canonical not in results["crypto"]:
                    results["crypto"].append(canonical)
                break

    for canonical, aliases in _STOCK_ENTITIES.items():
        for alias in aliases:
            if alias in text or alias.upper() in text_upper:
                if canonical not in results["stock"]:
                    results["stock"].append(canonical)
                break

    for canonical, aliases in _INDEX_ENTITIES.items():
        for alias in aliases:
            if alias in text:
                if canonical not in results["index"]:
                    results["index"].append(canonical)
                break

    for canonical, aliases in _PERSON_ENTITIES.items():
        for alias in aliases:
            if alias in text:
                if canonical not in results["person"]:
                    results["person"].append(canonical)
                break

    for canonical, aliases in _ORG_ENTITIES.items():
        for alias in aliases:
            if alias in text:
                if canonical not in results["org"]:
                    results["org"].append(canonical)
                break

    for theme, keywords in _THEME_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                if theme not in results["theme"]:
                    results["theme"].append(theme)
                break

    return results


def group_related_items(items: list[dict[str, Any]], title_key: str = "title") -> dict[str, list[dict[str, Any]]]:
    """Group news items by shared entities.

    Returns dict mapping group labels to lists of related items.
    Items sharing entities are grouped together.
    """
    # Extract entities for each item
    item_entities: list[tuple[dict, dict]] = []
    for item in items:
        title = item.get(title_key, "")
        desc = item.get("description", "")
        text = f"{title} {desc}"
        entities = extract_entities(text)
        item.setdefault("_entities", entities)
        item_entities.append((item, entities))

    # Build entity → items index
    entity_to_items: dict[str, list[int]] = defaultdict(list)
    for idx, (_, entities) in enumerate(item_entities):
        for category, names in entities.items():
            for name in names:
                key = f"{category}:{name}"
                entity_to_items[key].append(idx)

    # Find groups (entities shared by 2+ items)
    groups: dict[str, list[dict]] = {}
    used_indices: set[int] = set()

    # Sort by group size (largest first)
    sorted_entities = sorted(entity_to_items.items(), key=lambda x: len(x[1]), reverse=True)

    for entity_key, indices in sorted_entities:
        if len(indices) < 2:
            continue
        # Filter out already-grouped items
        new_indices = [i for i in indices if i not in used_indices]
        if len(new_indices) < 2:
            continue

        category, name = entity_key.split(":", 1)
        label = _format_group_label(category, name)
        group_items = [item_entities[i][0] for i in new_indices]
        groups[label] = group_items
        used_indices.update(new_indices)

    # Add ungrouped items
    ungrouped = [item_entities[i][0] for i in range(len(items)) if i not in used_indices]
    if ungrouped:
        groups["기타 뉴스"] = ungrouped

    return groups


def extract_market_signals(items: list[dict[str, Any]], title_key: str = "title") -> dict[str, Any]:
    """Extract market signal summary from a collection of news items.

    Returns a dict with signal counts and dominant themes.
    """
    all_entities: dict[str, list[str]] = defaultdict(list)
    theme_counts: dict[str, int] = defaultdict(int)

    for item in items:
        title = item.get(title_key, "")
        desc = item.get("description", "")
        text = f"{title} {desc}"
        entities = extract_entities(text)

        for category, names in entities.items():
            all_entities[category].extend(names)
        for theme in entities.get("theme", []):
            theme_counts[theme] += 1

    # Count entity frequencies
    entity_freq: dict[str, dict[str, int]] = {}
    for category, names in all_entities.items():
        freq: dict[str, int] = defaultdict(int)
        for name in names:
            freq[name] += 1
        entity_freq[category] = dict(sorted(freq.items(), key=lambda x: x[1], reverse=True))

    # Determine dominant themes
    sorted_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)

    return {
        "entity_frequencies": entity_freq,
        "dominant_themes": sorted_themes[:5],
        "total_items": len(items),
        "theme_coverage": len(theme_counts),
    }


def _format_group_label(category: str, name: str) -> str:
    """Format a human-readable group label."""
    _LABELS = {
        "crypto": {
            "bitcoin": "비트코인(BTC)",
            "ethereum": "이더리움(ETH)",
            "xrp": "XRP",
            "solana": "솔라나(SOL)",
        },
        "stock": {
            "nvidia": "엔비디아(NVDA)",
            "tesla": "테슬라(TSLA)",
            "apple": "애플(AAPL)",
            "samsung": "삼성전자",
        },
        "index": {"sp500": "S&P 500", "nasdaq": "나스닥", "kospi": "KOSPI", "vix": "VIX"},
        "person": {"trump": "트럼프", "powell": "파월 의장", "musk": "일론 머스크"},
        "org": {"fed": "연준(Fed)", "sec": "SEC", "binance": "바이낸스"},
        "theme": {},
    }
    label_map = _LABELS.get(category, {})
    return label_map.get(name, name)
