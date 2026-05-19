"""Tiny fixture: 4 articles, below the 5-item threshold (T1 in golden plan).

Targets the early-return guard at the top of
``ThemeSummarizer.generate_themed_news_sections``:

    if len(self.items) < 5:
        return ""

All 4 items hit the ``regulation`` theme keywords so only the count cutoff —
not the theme-detection failure — is exercised. The expected golden is the
empty string (verified after generation).
"""

ITEMS: list[dict] = [
    {
        "title": "SEC opens consultation on stablecoin reserves",
        "title_ko": None,
        "description": "Regulator invites industry comment on reserve-asset transparency standards.",
        "description_ko": None,
        "link": "https://example.com/sec/stablecoin-consultation",
        "image": "",
        "source": "Example Wire",
    },
    {
        "title": "CFTC commissioner outlines enforcement priorities",
        "title_ko": None,
        "description": "Speech sets out three focus areas for the coming fiscal year.",
        "description_ko": None,
        "link": "https://example.com/cftc/speech",
        "image": "",
        "source": "Example Wire",
    },
    {
        "title": "MiCA technical standards reach public comment phase",
        "title_ko": None,
        "description": "European authority publishes draft technical standards on whitepaper disclosures.",
        "description_ko": None,
        "link": "https://example.com/mica/its",
        "image": "",
        "source": "Example Brief",
    },
    {
        "title": "Compliance survey highlights audit gaps",
        "title_ko": None,
        "description": "Industry survey finds persistent shortfalls in internal compliance audits.",
        "description_ko": None,
        "link": "https://example.com/audit-survey",
        "image": "",
        "source": "Example Brief",
    },
]
