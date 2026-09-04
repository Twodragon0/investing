"""Fixture: English source titles that carry a Korean ``title_ko`` (2026-09-04).

Pins the wiring half of the body-blurb Korean guard on the production path.
``mixed_lang_with_synthetic_desc`` sets ``title_ko: None`` on every article, so
it only ever exercised the "no Korean rendition exists" branch. The far larger
population is the opposite one: a corpus scan on 2026-09-04 found 235 of 252
leaking blurbs sat directly beneath a card anchor that already showed Korean.

Those leaked because ``_render_featured_card`` handed the raw ``title`` to
``_generate_title_based_desc`` while rendering the anchor from ``title_ko``.
The rendered card must now show Korean in both places.

Construction:
- 6 articles across bitcoin, regulation and ai_tech so at least two themes
  clear the rendering threshold.
- Every article has an English ``title`` and a Korean ``title_ko``.
- 4 carry descriptions that the sanitizers reject (generic template, site
  boilerplate, description equal to the Korean title), forcing the fallback.
- 2 carry clean Korean descriptions so the happy path stays in the snapshot
  and a regression cannot pass by emptying the whole section.

Descriptions here are Korean on purpose. An English ``description`` would not
reach the fallback at all: it would pass the ``description != title`` check
(which compares against ``title_ko``) and render verbatim through the real
description branch — a separate, wider leak path left open on purpose, flagged
in ``_render_featured_card``.
"""

ITEMS: list[dict] = [
    # ---- Bitcoin (3) ----
    # Generic synthetic desc → rejected, falls back to the title synthesizer.
    {
        "title": "BTC price near $78,000 as Arbitrum surges on Robinhood Chain revenue",
        "title_ko": "BTC 가격이 아비트럼 급등에 힘입어 $78,000에 근접",
        "description": "",
        "description_ko": "암호화폐 관련 소식을 전했습니다.",
        "link": "https://example.com/btc/arbitrum",
        "image": "",
        "source": "Example Crypto",
    },
    # Generic synthetic desc → rejected, falls back.
    {
        "title": "Bitcoin halving narrative drives accumulation",
        "title_ko": "비트코인 반감기 서사가 매집을 이끈다",
        "description": "",
        "description_ko": "비트코인 관련 보도.",
        "link": "https://example.com/btc/halving",
        "image": "",
        "source": "Example Crypto",
    },
    # Clean Korean desc → renders normally, no fallback.
    {
        "title": "Spot bitcoin ETFs log third straight week of inflows",
        "title_ko": "현물 비트코인 ETF, 3주 연속 순유입 기록",
        "description": "",
        "description_ko": "현물 비트코인 ETF에 3주 연속 자금이 들어오며 누적 순유입이 사상 최대를 기록했다고 집계 기관이 밝혔습니다.",
        "link": "https://example.com/btc/etf-inflows",
        "image": "",
        "source": "Example Wire",
    },
    # ---- Regulation (3) ----
    # Site boilerplate desc → rejected, falls back.
    {
        "title": "MiCA framework consultation enters next phase",
        "title_ko": "미카(MiCA) 프레임워크 협의가 다음 단계로",
        "description": "",
        "description_ko": "우리의 목적은 세상을 더 잘 이해하도록 돕는 것입니다.",
        "link": "https://example.com/mica/phase",
        "image": "",
        "source": "Example Brief",
    },
    # Description repeats the Korean title verbatim → falls back.
    {
        "title": "SEC issues clarified disclosure guidance for registrants",
        "title_ko": "SEC, 등록법인 대상 공시 지침을 명확화",
        "description": "",
        "description_ko": "SEC, 등록법인 대상 공시 지침을 명확화",
        "link": "https://example.com/sec/disclosure",
        "image": "",
        "source": "Example Wire",
    },
    # Clean Korean desc → renders normally.
    {
        "title": "Treasury outlines stablecoin reserve reporting rules",
        "title_ko": "재무부, 스테이블코인 준비금 보고 규칙을 제시",
        "description": "",
        "description_ko": "재무부가 스테이블코인 발행사에 분기별 준비금 구성 내역을 제출하도록 요구하는 규칙 초안을 공개했습니다.",
        "link": "https://example.com/treasury/stablecoin",
        "image": "",
        "source": "Example Brief",
    },
]
