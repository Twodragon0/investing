"""Small fixture: 6 articles in the `regulation` theme.

Targets the single-theme card-then-overflow branch (T2 in golden plan):
- 6 items, all hitting `regulation` keywords (sec / cftc / regulation / mica).
- 3 items have `description`, 1 also has `description_ko`, 2 have no
  description (exercises the `_generate_title_based_desc` fallback branch).
- 1 item has an `image` URL (thumbnail branch), 1 has only `link` (favicon
  fallback branch), 4 have neither (no-thumbnail branch).
- All titles are English-only so the severity classifier returns the same
  bucket (`medium` — none of the high/low keyword sets match), keeping the
  card badges deterministic.

featured_count=3, max_articles=5 (default `ARTICLES_PER_THEME`).
"""

ITEMS: list[dict] = [
    {
        "title": "SEC clarifies stablecoin guidance for issuers",
        "title_ko": None,
        "description": "Federal regulator publishes interpretive guidance covering reserve disclosures and redemption mechanics.",
        "description_ko": None,
        "link": "https://example.com/sec/stablecoin-guidance",
        "image": "https://example.com/img/sec-building.jpg",
        "source": "Example Wire",
    },
    {
        "title": "CFTC enforcement sweep targets unregistered platforms",
        "title_ko": None,
        "description": "Commission opens parallel actions against three offshore exchanges allegedly serving retail traders without registration.",
        "description_ko": "위원회가 미등록 거래소에 대한 집행 절차를 개시했습니다.",
        "link": "https://example.com/cftc/sweep",
        "image": "",
        "source": "Example Wire",
    },
    {
        "title": "Regulation roundtable convenes on market structure",
        "title_ko": None,
        "description": "Industry groups and lawmakers discuss spot-market oversight under the proposed market structure bill.",
        "description_ko": None,
        "link": "",
        "image": "",
        "source": "Example Brief",
    },
    {
        "title": "MiCA implementing technical standards open for comment",
        "title_ko": None,
        "description": "",
        "description_ko": None,
        "link": "https://example.com/mica/its-consultation",
        "image": "",
        "source": "Example Brief",
    },
    {
        "title": "Compliance officers warn on audit gaps in CBDC pilots",
        "title_ko": None,
        "description": "",
        "description_ko": None,
        "link": "",
        "image": "",
        "source": "",
    },
    {
        "title": "Self regulatory body proposes lawsuit-disclosure rule",
        "title_ko": None,
        "description": "",
        "description_ko": None,
        "link": "",
        "image": "",
        "source": "Example Brief",
    },
]
