"""Image variants fixture: 8 articles, 4 image-rendering branches (T8).

Targets the thumbnail vs favicon vs no-thumbnail decision at L754-773 of
``generate_themed_news_sections``:

1. Normal article image — renders ``.news-card-thumb`` with the image URL.
2. Logo-like URL (matches ``is_logo_like_url`` patterns such as ``/logo/``)
   — image is rejected, falls back to favicon (link is present).
3. No image, but link present — favicon fallback path.
4. No image AND no link — no thumbnail rendered at all.

All 8 articles target the ``regulation`` and ``bitcoin`` themes so the
``stub_favicon`` monkeypatch is exercised on every fallback row.
"""

ITEMS: list[dict] = [
    # ---- Regulation (4) ----
    # 1) Normal image — thumbnail rendered
    {
        "title": "SEC publishes interpretive guidance for issuers",
        "title_ko": None,
        "description": "Federal regulator clarifies expectations on reserve disclosures.",
        "description_ko": None,
        "link": "https://example.com/sec/guidance",
        "image": "https://example.com/img/sec-building.jpg",
        "source": "Example Wire",
    },
    # 2) Logo-like image URL — should be rejected, favicon fallback (link present)
    {
        "title": "CFTC announces enforcement sweep",
        "title_ko": None,
        "description": "Commission opens parallel actions against unregistered platforms.",
        "description_ko": None,
        "link": "https://example.com/cftc/sweep",
        "image": "https://example.com/assets/logo/cftc-logo.png",
        "source": "Example Wire",
    },
    # 3) No image, link present — favicon fallback
    {
        "title": "MiCA technical standards open for comment",
        "title_ko": None,
        "description": "European authority publishes draft technical standards for stakeholder input.",
        "description_ko": None,
        "link": "https://example.com/mica/its",
        "image": "",
        "source": "Example Brief",
    },
    # 4) No image AND no link — no thumbnail at all
    {
        "title": "Compliance audit reveals systemic gaps",
        "title_ko": None,
        "description": "Industry-wide review finds persistent shortfalls in internal compliance audits.",
        "description_ko": None,
        "link": "",
        "image": "",
        "source": "Example Brief",
    },
    # ---- Bitcoin (4) — same 4 variants ----
    # 1) Normal image
    {
        "title": "Bitcoin spot ETF inflows accelerate",
        "title_ko": None,
        "description": "Daily creation activity pushes weekly net inflows to a multi-month high.",
        "description_ko": None,
        "link": "https://example.com/btc/etf",
        "image": "https://example.com/img/btc-chart.jpg",
        "source": "Example Crypto",
    },
    # 2) Logo-like image
    {
        "title": "Bitcoin miners report record hash rate",
        "title_ko": None,
        "description": "Network hash rate reaches new all-time high as ASIC deployment continues.",
        "description_ko": None,
        "link": "https://example.com/btc/hashrate",
        "image": "https://example.com/static/icons/btc-icon.png",
        "source": "Example Crypto",
    },
    # 3) No image, link present
    {
        "title": "Bitcoin halving narrative drives accumulation",
        "title_ko": None,
        "description": "On-chain analysts highlight increased holdings by long-term wallets.",
        "description_ko": None,
        "link": "https://example.com/btc/halving",
        "image": "",
        "source": "Example Crypto",
    },
    # 4) No image AND no link
    {
        "title": "Bitcoin treasury strategy gains corporate interest",
        "title_ko": None,
        "description": "Public companies signal interest in adding bitcoin to corporate treasury.",
        "description_ko": None,
        "link": "",
        "image": "",
        "source": "Example Crypto",
    },
]
