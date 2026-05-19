"""Cross-theme dedup heavy fixture: 12 articles, multi-theme keyword overlap (T5).

Targets the ``cross_theme_featured`` demotion path at L727-737 of
``ThemeSummarizer.generate_themed_news_sections``. Same article shows up as
the top match for theme A; when theme B iterates, the same title is already
in ``cross_theme_featured`` and gets pushed into the overflow ``remaining_links``
list instead of being rendered as a #1 card again.

Construction:
- Themes hit (by THEMES order): regulation, bitcoin, exchange, macro.
- 8 of 12 articles match a single theme cleanly.
- 4 articles ("cross_*") carry keywords for both regulation+bitcoin or
  regulation+exchange so they appear in *both* theme buckets. Regulation
  ranks higher in this fixture so it features the cross-articles first; the
  bitcoin/exchange iterations then demote them.

All titles are English so severity tagging stays deterministic ("warn",
"crash" intentionally avoided where not desired).
"""

ITEMS: list[dict] = [
    # ---- Cross-theme: regulation + bitcoin (2) — placed FIRST so they
    # occupy regulation featured slots #1/#2 and end up in
    # ``cross_theme_featured``. The bitcoin section iteration then demotes
    # them via the L727-737 path. ----
    {
        "title": "SEC clarifies bitcoin ETF reporting requirements",
        "title_ko": None,
        "description": "Staff guidance addresses creation and redemption disclosures for spot bitcoin ETF issuers.",
        "description_ko": None,
        "link": "https://example.com/sec/btc-etf",
        "image": "",
        "source": "Example Wire",
    },
    {
        "title": "CFTC opens consultation on bitcoin derivatives",
        "title_ko": None,
        "description": "Commission seeks public input on margin treatment for spot-referenced bitcoin contracts.",
        "description_ko": None,
        "link": "https://example.com/cftc/btc-derivs",
        "image": "",
        "source": "Example Wire",
    },
    # ---- Cross-theme: regulation + exchange (1) — third featured slot
    # so the exchange iteration also has a demotion to demonstrate. ----
    {
        "title": "Regulation roundtable convenes on exchange listings",
        "title_ko": None,
        "description": "Industry groups and supervisors discuss listing standards as part of broader market structure work.",
        "description_ko": None,
        "link": "https://example.com/roundtable/listings",
        "image": "",
        "source": "Example Brief",
    },
    # ---- Regulation-only (3) — overflow in regulation section. ----
    {
        "title": "SEC publishes clarified guidance for issuers",
        "title_ko": None,
        "description": "Staff statement addresses recurring questions from registrants about disclosure obligations.",
        "description_ko": None,
        "link": "https://example.com/sec/guidance",
        "image": "",
        "source": "Example Wire",
    },
    {
        "title": "MiCA technical standards proceed to comment",
        "title_ko": None,
        "description": "European authority publishes draft technical standards for stakeholder consultation.",
        "description_ko": None,
        "link": "https://example.com/mica/its",
        "image": "",
        "source": "Example Brief",
    },
    {
        "title": "DOJ enforcement priorities update issued",
        "title_ko": None,
        "description": "Department issues updated enforcement priorities document for the upcoming fiscal year.",
        "description_ko": None,
        "link": "https://example.com/doj/priorities",
        "image": "",
        "source": "Example Brief",
    },
    # ---- Cross-theme: regulation + exchange (1 more, lands in overflow). ----
    {
        "title": "Compliance audit covers exchange custodian practices",
        "title_ko": None,
        "description": "Audit programme reviews custodian segregation procedures across major exchange platforms.",
        "description_ko": None,
        "link": "https://example.com/audit/custodian",
        "image": "",
        "source": "Example Brief",
    },
    # ---- Bitcoin-only (2) ----
    {
        "title": "Bitcoin miners report network hash rate gains",
        "title_ko": None,
        "description": "Operators highlight steady deployment of next-generation rigs and improving network economics.",
        "description_ko": None,
        "link": "https://example.com/btc/hashrate",
        "image": "",
        "source": "Example Crypto",
    },
    {
        "title": "Bitcoin halving cycle analysis released",
        "title_ko": None,
        "description": "Research note examines on-chain accumulation patterns ahead of the next supply schedule.",
        "description_ko": None,
        "link": "https://example.com/btc/halving",
        "image": "",
        "source": "Example Crypto",
    },
    # ---- Exchange-only (1) ----
    {
        "title": "Binance launches new perpetual contracts lineup",
        "title_ko": None,
        "description": "Exchange expands derivatives offering with additional perpetual swap markets.",
        "description_ko": None,
        "link": "https://example.com/binance/perp",
        "image": "",
        "source": "Example Exchange",
    },
    # ---- Macro-only (2) — keeps macro just barely qualifying ----
    {
        "title": "Fed rate path watched by market participants",
        "title_ko": None,
        "description": "Investors parse FOMC minutes for signals on the pace of future rate decisions.",
        "description_ko": None,
        "link": "https://example.com/fed/path",
        "image": "",
        "source": "Example Macro",
    },
    {
        "title": "CPI release shapes inflation expectations",
        "title_ko": None,
        "description": "Headline and core inflation figures match consensus while shelter remains the largest contributor.",
        "description_ko": None,
        "link": "https://example.com/cpi/release",
        "image": "",
        "source": "Example Macro",
    },
]
