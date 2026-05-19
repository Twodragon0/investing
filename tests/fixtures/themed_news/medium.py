"""Medium fixture: 20 articles spanning 5 themes (T3 in golden plan).

Targets the cross-theme dedup path:
- 4 themes are well populated (regulation, macro, bitcoin, exchange, ai_tech)
  so ``get_top_themes()`` returns up to ``TOP_THEMES_COUNT=5`` themes.
- A handful of articles intentionally carry keywords from multiple themes so
  the *same* article can resurface in a second theme bucket where the
  ``cross_theme_featured`` set demotes it into the overflow list.
- Most cards have descriptions and links so the standard card branch is
  exercised; a few omit images/links to keep `_favicon_url` stubbing
  predictable.

Mixed severity by design — titles include "surge"/"crash"/"warn" to trip the
high-severity classifier on a subset and leave the rest at medium.
"""

ITEMS: list[dict] = [
    # Regulation theme
    {
        "title": "SEC stablecoin guidance gains industry support",
        "title_ko": None,
        "description": "Federal regulator issues clarified expectations on reserve disclosures and redemption mechanics.",
        "description_ko": None,
        "link": "https://example.com/sec/stablecoin",
        "image": "https://example.com/img/sec.jpg",
        "source": "Example Wire",
    },
    {
        "title": "CFTC sweep targets unregistered offshore platforms",
        "title_ko": None,
        "description": "Commission opens parallel actions covering three exchanges allegedly serving retail traders without registration.",
        "description_ko": None,
        "link": "https://example.com/cftc/sweep",
        "image": "",
        "source": "Example Wire",
    },
    {
        "title": "MiCA implementing technical standards open for comment",
        "title_ko": None,
        "description": "European authority publishes technical standards on whitepaper disclosures and supervisory cooperation.",
        "description_ko": None,
        "link": "https://example.com/mica/its",
        "image": "",
        "source": "Example Brief",
    },
    {
        "title": "Lawsuit against major issuer enters discovery phase",
        "title_ko": None,
        "description": "Court order sets schedule for production of internal compliance records and reserve attestations.",
        "description_ko": None,
        "link": "https://example.com/lawsuit/discovery",
        "image": "",
        "source": "Example Brief",
    },
    # Macro theme (rate / fed / inflation)
    {
        "title": "Fed warns inflation may persist into next year",
        "title_ko": None,
        "description": "FOMC minutes show policymakers concerned about sticky services prices and wage pressures.",
        "description_ko": None,
        "link": "https://example.com/fed/fomc",
        "image": "https://example.com/img/fed.jpg",
        "source": "Example Macro",
    },
    {
        "title": "Treasury yields surge after CPI surprise",
        "title_ko": None,
        "description": "Bond market reprices rate-cut expectations following hotter-than-expected inflation print.",
        "description_ko": None,
        "link": "https://example.com/treasury/cpi",
        "image": "",
        "source": "Example Macro",
    },
    {
        "title": "ECB officials signal patience on rate cuts",
        "title_ko": None,
        "description": "Governing council members emphasize data-dependent path while inflation remains above target.",
        "description_ko": None,
        "link": "https://example.com/ecb/patience",
        "image": "",
        "source": "Example Macro",
    },
    {
        "title": "Powell speech keeps door open on policy path",
        "title_ko": None,
        "description": "Fed chair reiterates commitment to dual mandate while maintaining flexibility on rate decisions.",
        "description_ko": None,
        "link": "https://example.com/powell",
        "image": "",
        "source": "Example Macro",
    },
    # Bitcoin theme
    {
        "title": "Bitcoin spot ETF inflows accelerate",
        "title_ko": None,
        "description": "Daily creation activity pushes weekly net inflows to a multi-month high across major issuers.",
        "description_ko": None,
        "link": "https://example.com/btc/etf",
        "image": "https://example.com/img/btc.jpg",
        "source": "Example Crypto",
    },
    {
        "title": "Bitcoin miners report record hash rate",
        "title_ko": None,
        "description": "Network hash rate reaches new all-time high as next-generation ASIC deployment continues.",
        "description_ko": None,
        "link": "https://example.com/btc/hashrate",
        "image": "",
        "source": "Example Crypto",
    },
    {
        "title": "Bitcoin halving narrative drives accumulation",
        "title_ko": None,
        "description": "On-chain analysts highlight increased holdings by long-term wallets ahead of the supply schedule.",
        "description_ko": None,
        "link": "https://example.com/btc/halving",
        "image": "",
        "source": "Example Crypto",
    },
    # Cross-theme: bitcoin + regulation (will hit regulation first, demoted in bitcoin)
    {
        "title": "SEC clarifies bitcoin ETF reporting requirements",
        "title_ko": None,
        "description": "Staff guidance addresses creation and redemption disclosures for spot bitcoin ETF issuers.",
        "description_ko": None,
        "link": "https://example.com/sec/btc-etf",
        "image": "",
        "source": "Example Wire",
    },
    # Exchange theme
    {
        "title": "Binance lists new perpetual contracts",
        "title_ko": None,
        "description": "Exchange expands derivatives lineup with three new perpetual swap markets for major altcoins.",
        "description_ko": None,
        "link": "https://example.com/binance/perp",
        "image": "https://example.com/img/binance.jpg",
        "source": "Example Exchange",
    },
    {
        "title": "Coinbase volume rises on derivatives launch",
        "title_ko": None,
        "description": "International derivatives venue contributes to quarterly volume growth alongside spot activity.",
        "description_ko": None,
        "link": "https://example.com/coinbase/derivatives",
        "image": "",
        "source": "Example Exchange",
    },
    {
        "title": "Upbit delisting affects three altcoins",
        "title_ko": None,
        "description": "Korean exchange announces removal of low-volume pairs as part of routine listing review.",
        "description_ko": None,
        "link": "https://example.com/upbit/delisting",
        "image": "",
        "source": "Example Exchange",
    },
    # AI/tech theme
    {
        "title": "Nvidia introduces next-generation AI chip lineup",
        "title_ko": None,
        "description": "Company unveils refreshed accelerator family targeting large-scale training and inference workloads.",
        "description_ko": None,
        "link": "https://example.com/nvidia/chip",
        "image": "https://example.com/img/nvidia.jpg",
        "source": "Example Tech",
    },
    {
        "title": "OpenAI extends enterprise tier with new tooling",
        "title_ko": None,
        "description": "Company adds workspace controls and audit features aimed at regulated enterprise deployments.",
        "description_ko": None,
        "link": "https://example.com/openai/enterprise",
        "image": "",
        "source": "Example Tech",
    },
    {
        "title": "Anthropic publishes safety research roadmap",
        "title_ko": None,
        "description": "Research agenda outlines investment in interpretability tooling and adversarial evaluations.",
        "description_ko": None,
        "link": "https://example.com/anthropic/roadmap",
        "image": "",
        "source": "Example Tech",
    },
    # Cross-theme: ai_tech + macro (will likely land in ai_tech as best match)
    {
        "title": "TSMC capex plan watched by macro analysts",
        "title_ko": None,
        "description": "Foundry capital spending plans signal industry confidence relevant to broader economic outlook.",
        "description_ko": None,
        "link": "https://example.com/tsmc/capex",
        "image": "",
        "source": "Example Tech",
    },
    # Cross-theme: exchange + regulation (will hit regulation first)
    {
        "title": "Regulation roundtable convenes on exchange listings",
        "title_ko": None,
        "description": "Industry groups and supervisors discuss listing standards as part of broader market structure work.",
        "description_ko": None,
        "link": "https://example.com/roundtable/listings",
        "image": "",
        "source": "Example Brief",
    },
]
