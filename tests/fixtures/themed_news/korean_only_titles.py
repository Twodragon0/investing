"""Korean-only titles fixture: 8 articles with ``title_ko`` (T6 in golden plan).

Targets the ``_fix_mistranslations`` branch that applies whenever the title
already exists in Korean (``title_ko``) and confirms severity classification
stays stable for Korean keyword hits ("급등", "급락", "금리", "규제").

Themes hit:
- regulation (4 articles — 금감원/금융위/규제/처분 keywords)
- macro (4 articles — 금리/기준금리/물가/한국은행 keywords)

All items carry ``title_ko`` plus a Korean ``description_ko`` so the card
body uses the Korean description path. Source/link fields kept consistent
to keep the favicon-fallback branch deterministic.
"""

ITEMS: list[dict] = [
    # Regulation (4)
    {
        "title": "Korean financial supervisor publishes new guidance",
        "title_ko": "금감원, 가상자산 거래소 신규 가이던스 공개",
        "title_original": "Korean financial supervisor publishes new guidance",
        "description": "FSS releases guidance on virtual asset exchange supervision.",
        "description_ko": "금감원이 가상자산 거래소 감독을 위한 가이던스를 공개했습니다.",
        "link": "https://example.com/fss/guidance",
        "image": "",
        "source": "예제 와이어",
    },
    {
        "title": "FSC announces enforcement priorities",
        "title_ko": "금융위, 자본시장법 집행 우선순위 발표",
        "title_original": "FSC announces enforcement priorities",
        "description": "Financial Services Commission outlines compliance focus for the year.",
        "description_ko": "금융위원회가 올해 자본시장법 집행의 중점 분야를 공개했습니다.",
        "link": "https://example.com/fsc/priorities",
        "image": "",
        "source": "예제 와이어",
    },
    {
        "title": "Regulation roundtable highlights market structure",
        "title_ko": "규제 라운드테이블, 시장 구조 개편 논의",
        "title_original": "Regulation roundtable highlights market structure",
        "description": "Industry and lawmakers discuss spot-market oversight.",
        "description_ko": "업계와 입법부가 현물시장 감독 방안을 논의했습니다.",
        "link": "https://example.com/roundtable/structure",
        "image": "",
        "source": "예제 브리프",
    },
    {
        "title": "Authority issues sanctions on unregistered exchange",
        "title_ko": "당국, 미등록 거래소에 제재 처분 부과",
        "title_original": "Authority issues sanctions on unregistered exchange",
        "description": "Sanctions decision finalised after multi-month investigation.",
        "description_ko": "다수 개월에 걸친 조사 끝에 미등록 거래소에 대한 제재 처분이 확정되었습니다.",
        "link": "https://example.com/sanction/exchange",
        "image": "",
        "source": "예제 브리프",
    },
    # Macro (4) — severity should trip "high" via "급등"/"인하"/"금리" tokens
    {
        "title": "BOK signals patience on rate decisions",
        "title_ko": "한국은행, 기준금리 결정에 신중 기조 시사",
        "title_original": "BOK signals patience on rate decisions",
        "description": "Bank of Korea highlights data-dependent stance.",
        "description_ko": "한국은행이 데이터 기반 기조를 강조했습니다.",
        "link": "https://example.com/bok/rate",
        "image": "",
        "source": "예제 매크로",
    },
    {
        "title": "Inflation surprise lifts yields",
        "title_ko": "물가 서프라이즈에 채권금리 급등",
        "title_original": "Inflation surprise lifts yields",
        "description": "Headline inflation print exceeds consensus, lifting bond yields.",
        "description_ko": "헤드라인 물가가 시장 예상을 상회하면서 채권금리가 급등했습니다.",
        "link": "https://example.com/cpi/yields",
        "image": "",
        "source": "예제 매크로",
    },
    {
        "title": "Fed minutes reveal cautious tone",
        "title_ko": "연준 의사록, 금리 인하에 신중한 기조",
        "title_original": "Fed minutes reveal cautious tone",
        "description": "FOMC minutes highlight inflation persistence concerns.",
        "description_ko": "FOMC 의사록은 물가 지속에 대한 우려를 강조했습니다.",
        "link": "https://example.com/fed/minutes",
        "image": "",
        "source": "예제 매크로",
    },
    {
        "title": "Korea CPI release shapes outlook",
        "title_ko": "국내 소비자물가 발표, 시장 전망 좌우",
        "title_original": "Korea CPI release shapes outlook",
        "description": "Headline and core figures meet expectations.",
        "description_ko": "헤드라인과 근원 소비자물가가 시장 예상과 부합했습니다.",
        "link": "https://example.com/kr/cpi",
        "image": "",
        "source": "예제 매크로",
    },
]
