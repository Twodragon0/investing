"""Mixed-language fixture with synthetic/boilerplate descriptions (T7).

Targets the three description sanitization branches at L787-797:
- ``_is_generic_desc`` filters known synthetic templates (e.g. "관련 보도.").
- ``_is_boilerplate_desc`` filters Korean site boilerplate phrases ("우리의
  목적은 세상을 …").
- When both descriptions are filtered (or the description equals the title),
  the renderer falls back to ``_generate_title_based_desc`` to synthesize a
  short analytical sentence from the title and theme key.

Construction:
- 10 articles spanning regulation, bitcoin, ai_tech themes.
- 4 articles carry generic synthetic descriptions matching the
  ``_GENERIC_DESC_PATTERNS`` list.
- 2 articles carry boilerplate descriptions ("우리의 목적은 …").
- 2 articles have descriptions identical to the title (forces fallback).
- 2 articles have clean descriptions to keep at least one good card per
  theme so the snapshot also covers the happy path.
"""

ITEMS: list[dict] = [
    # ---- Regulation (4) ----
    # Clean desc — should render normally
    {
        "title": "SEC issues clarified disclosure guidance",
        "title_ko": None,
        "description": "Staff statement addresses recurring questions from registrants about reserve disclosures.",
        "description_ko": None,
        "link": "https://example.com/sec/disclosure",
        "image": "",
        "source": "Example Wire",
    },
    # Generic synthetic desc — matches "관련 보도." trailing pattern
    {
        "title": "MiCA framework consultation enters next phase",
        "title_ko": None,
        "description": "",
        "description_ko": "규제 관련 보도.",
        "link": "https://example.com/mica/phase",
        "image": "",
        "source": "Example Brief",
    },
    # Boilerplate desc — Motley Fool style site boilerplate
    {
        "title": "CFTC reviews enforcement priorities for fiscal year",
        "title_ko": None,
        "description": "Motley Fool — our purpose is to make the world smarter and happier.",
        "description_ko": None,
        "link": "https://example.com/cftc/priorities",
        "image": "",
        "source": "Example Wire",
    },
    # Description equals title — forces fallback
    {
        "title": "Lawsuit against issuer enters discovery phase",
        "title_ko": None,
        "description": "Lawsuit against issuer enters discovery phase",
        "description_ko": None,
        "link": "https://example.com/lawsuit/discovery",
        "image": "",
        "source": "Example Brief",
    },
    # ---- Bitcoin (3) ----
    # Clean desc
    {
        "title": "Bitcoin spot ETF inflows accelerate",
        "title_ko": None,
        "description": "Daily creation activity pushes weekly net inflows to a multi-month high across major issuers.",
        "description_ko": None,
        "link": "https://example.com/btc/etf",
        "image": "",
        "source": "Example Crypto",
    },
    # Generic synthetic desc — matches "에서 보도한 뉴스입니다."
    {
        "title": "Bitcoin halving narrative drives accumulation",
        "title_ko": None,
        "description": "",
        "description_ko": "예제 출처에서 보도한 뉴스입니다.",
        "link": "https://example.com/btc/halving",
        "image": "",
        "source": "Example Crypto",
    },
    # Boilerplate desc — Seeking Alpha style site boilerplate
    {
        "title": "Bitcoin miner reports record hash rate",
        "title_ko": None,
        "description": "Seeking Alpha — our purpose is to provide actionable investment ideas.",
        "description_ko": None,
        "link": "https://example.com/btc/miner",
        "image": "",
        "source": "Example Crypto",
    },
    # ---- AI/tech (3) ----
    # Clean desc
    {
        "title": "Nvidia unveils next-generation AI chip lineup",
        "title_ko": None,
        "description": "Company refreshes accelerator family targeting large-scale training and inference workloads.",
        "description_ko": None,
        "link": "https://example.com/nvidia/lineup",
        "image": "",
        "source": "Example Tech",
    },
    # Generic synthetic desc — matches "확인하세요." trailing pattern
    {
        "title": "OpenAI publishes enterprise feature roadmap",
        "title_ko": None,
        "description": "",
        "description_ko": "원문에서 세부 내용을 확인하세요.",
        "link": "https://example.com/openai/roadmap",
        "image": "",
        "source": "Example Tech",
    },
    # Description equals title — forces fallback
    {
        "title": "Anthropic publishes safety research roadmap",
        "title_ko": None,
        "description": "Anthropic publishes safety research roadmap",
        "description_ko": None,
        "link": "https://example.com/anthropic/safety",
        "image": "",
        "source": "Example Tech",
    },
]
