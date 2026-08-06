"""Punctuation edge cases: the text-mangling classes the other 8 fixtures miss.

The 2026-08-06 hyphen regression reached `main` and truncated 13 published
blurbs before a golden caught it — and the golden that caught it
(``image_variants``) did so *by accident*, because one of its descriptions
happened to contain "multi-month". No fixture targeted the punctuation rules
on purpose, so the safety net had a hole exactly where the edit was risky.

Each article below pins one rule, in both directions where that applies:

1. Hyphen compound in the description — must survive. A delimiter needs
   whitespace in front of it; `multi-month` does not have any.
2. Hyphen compound in the *title* — the two title-cleaning paths had the same
   bug ("(BTC-USD:Cryptocurrency)" → "(BTC").
3. Source suffix with a leading space — must be stripped, since the card
   already renders the outlet in its own `source-tag` span.
4. Source suffix glued on without a space — must be kept. This is the
   deliberate cost of rule 1: a false positive destroys a sentence, a false
   negative leaves a name behind.
5. Ellipsis `...` — deliberate Korean punctuation, must survive the
   doubled-period collapse that targets `..`.
6. Pipe-delimited navigation strip — site chrome, must not reach the card as
   an article summary.

All articles target ``bitcoin`` so theme classification stays deterministic
and every row goes through the same rendering branch.
"""

ITEMS: list[dict] = [
    # 1) Hyphen compound in the description — tail must survive.
    {
        "title": "비트코인 현물 ETF 자금 유입 가속",
        "title_ko": None,
        "description": "Daily creation activity pushes weekly net inflows to a multi-month high.",
        "description_ko": None,
        "link": "https://example.com/btc/etf-inflows",
        "image": "https://example.com/img/etf.jpg",
        "source": "Example Crypto",
    },
    # 2) Hyphen compound in the title — "(BTC-USD:Cryptocurrency)" must stay whole.
    {
        "title": "금리 인하 기대 약화로 암호화폐 주가 급락 (BTC-USD:Cryptocurrency)",
        "title_ko": None,
        "description": "선물 미결제약정이 줄면서 변동성이 확대됐다고 거래소가 밝혔습니다.",
        "description_ko": None,
        "link": "https://example.com/btc/rate-cut",
        "image": "https://example.com/img/rates.jpg",
        "source": "Example Crypto",
    },
    # 3) Source suffix with a leading space — stripped.
    {
        "title": "비트코인 채굴 난이도 사상 최고치 경신",
        "title_ko": None,
        "description": "S&P500·나스닥 급락; 원유·가스 급등; 비트코인이 $67K 근처로 후퇴했습니다 - The Sunday Guardian",
        "description_ko": None,
        "link": "https://example.com/btc/difficulty",
        "image": "https://example.com/img/mining.jpg",
        "source": "Example Crypto",
    },
    # 4) Source glued on without a space — kept, by design.
    {
        "title": "비트코인 반등에 알트코인 동반 상승",
        "title_ko": None,
        "description": "트럼프 대통령이 암호화폐 법안을 공개 지지하면서 시장이 반등했다고 전해집니다-[美증시 특징주]",
        "description_ko": None,
        "link": "https://example.com/btc/altcoin-rally",
        "image": "https://example.com/img/altcoin.jpg",
        "source": "Example Crypto",
    },
    # 5) Ellipsis — survives the `..` collapse.
    {
        "title": "비트코인 장중 급락 후 낙폭 축소",
        "title_ko": None,
        "description": "비트코인·알트코인 '장중 급락'...주요 변수는 금리와 환율이라는 분석이 나왔습니다.",
        "description_ko": None,
        "link": "https://example.com/btc/intraday",
        "image": "https://example.com/img/intraday.jpg",
        "source": "Example Crypto",
    },
    # 6) Navigation strip — site chrome, must not render as a summary.
    {
        "title": "비트코인 규제 논의 지역 의회로 확산",
        "title_ko": None,
        "description": "KCRG | 시더 래피즈, 아이오와 시티, 워털루, 더뷰크 | 뉴스, 스포츠, 날씨",
        "description_ko": None,
        "link": "https://example.com/btc/local-regulation",
        "image": "https://example.com/img/local.jpg",
        "source": "Example Crypto",
    },
]
