"""generate_daily_summary — 감성/관계/데이터 추출 헬퍼 (L1).

`summary_sections.py` 에서 추출(2026-06-29, L2 분리 캠페인). 감성 분석, 교차자산
토픽 스코어링, 관계 추출, 카테고리 데이터 포인트, 생성 이미지 마크다운 등 중간
레이어 헬퍼. L0([[summary-text-ko]])에만 의존하고 섹션 빌더(L2)는 호출하지 않는다.
메인 모듈/테스트는 gds.<name> 으로 재-export 참조한다.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple  # noqa: F401

from common.markdown_utils import smart_truncate
from common.post_generator import POSTS_DIR
from common.summary_text_ko import _is_noise_title

logger = logging.getLogger("daily-summary")


def _cross_asset_topics() -> Dict[str, List[str]]:
    return {
        "금리/유동성": [
            "금리",
            "연준",
            "fed",
            "fomc",
            "유동성",
            "국채",
            "yield",
            "기준금리",
            "인하",
            "인상",
            "양적",
            "긴축",
            "완화",
            "pivot",
        ],
        "환율/달러": [
            "환율",
            "usd/krw",
            "달러",
            "dxy",
            "원화",
            "엔화",
            "위안",
            "강달러",
            "약달러",
            "환헤지",
        ],
        "정책/규제": [
            "규제",
            "sec",
            "etf",
            "법안",
            "정책",
            "행정명령",
            "tariff",
            "관세",
            "승인",
            "거부",
            "감독",
            "제재",
            "스테이블코인",
            "자금세탁",
            "aml",
            "kyc",
            "mifid",
        ],
        "리스크 이벤트": [
            "해킹",
            "exploit",
            "파산",
            "청산",
            "liquidation",
            "보안사고",
            "러그풀",
            "디페깅",
            "depeg",
            "공격",
            "취약점",
            "유출",
        ],
        "수급/심리": [
            "고래",
            "whale",
            "수급",
            "공포",
            "탐욕",
            "sentiment",
            "social",
            "거래량",
            "미결제약정",
            "open interest",
            "펀딩비",
            "매수",
            "매도",
            "롱",
            "숏",
            "청산량",
        ],
        "실적/지표": [
            "실적",
            "cpi",
            "pce",
            "고용",
            "매출",
            "earnings",
            "gdp",
            "ism",
            "pmi",
            "소비자신뢰",
            "실업률",
            "비농업",
        ],
        "기술/온체인": [
            "tvl",
            "defi",
            "nft",
            "레이어2",
            "l2",
            "업그레이드",
            "하드포크",
            "반감기",
            "halving",
            "해시레이트",
            "gas",
        ],
        "지정학": [
            "전쟁",
            "분쟁",
            "제재",
            "opec",
            "원유",
            "에너지",
            "중국",
            "러시아",
            "대만",
            "nato",
            "무역전쟁",
        ],
    }


def _sentiment_keywords() -> Dict[str, List[str]]:
    """Keywords for positive/negative sentiment classification."""
    return {
        "positive": [
            "상승",
            "급등",
            "반등",
            "돌파",
            "신고가",
            "강세",
            "호재",
            "승인",
            "확대",
            "성장",
            "개선",
            "회복",
            "상향",
            "증가",
            "rally",
            "bull",
            "surge",
            "breakout",
            "upgrade",
            "adoption",
            "매수",
            "유입",
            "낙관",
            "기대감",
            "사상최고",
        ],
        "negative": [
            "하락",
            "급락",
            "폭락",
            "약세",
            "악재",
            "위험",
            "경고",
            "해킹",
            "파산",
            "소송",
            "제재",
            "규제",
            "위축",
            "감소",
            "crash",
            "bear",
            "dump",
            "hack",
            "exploit",
            "fraud",
            "매도",
            "유출",
            "공포",
            "불안",
            "하향",
            "적자",
        ],
    }


def _analyze_sentiment(summaries: List[Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """Analyze sentiment across all summaries by counting keyword hits in titles and content."""
    pos_kw = _sentiment_keywords()["positive"]
    neg_kw = _sentiment_keywords()["negative"]

    pos_count = 0
    neg_count = 0
    pos_examples: List[str] = []
    neg_examples: List[str] = []

    for s in summaries:
        if not s or not s.get("content"):
            continue
        # Analyze titles extracted from bullet points and headings
        titles = []
        content = s["content"]
        for line in content.split("\n"):
            line = line.strip()
            # Extract titles from markdown links
            for m in re.finditer(r"\[([^\]]+)\]", line):
                titles.append(m.group(1))
            # Extract from bold text
            for m in re.finditer(r"\*\*([^*]+)\*\*", line):
                titles.append(m.group(1))

        for title in titles:
            t_lower = title.lower()
            # Strip markdown link syntax to get plain text for display
            display_title = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", title).strip()
            display_title = display_title.lstrip("0123456789. ")
            for kw in pos_kw:
                if kw in t_lower:
                    pos_count += 1
                    if len(pos_examples) < 3 and len(display_title) > 10:
                        if display_title not in pos_examples:
                            pos_examples.append(smart_truncate(display_title, 120))
                    break
            for kw in neg_kw:
                if kw in t_lower:
                    neg_count += 1
                    if len(neg_examples) < 3 and len(display_title) > 10:
                        if display_title not in neg_examples:
                            neg_examples.append(smart_truncate(display_title, 120))
                    break

    total = pos_count + neg_count
    if total == 0:
        tone = "중립"
        ratio = 50
    else:
        ratio = round(pos_count / total * 100)
        if ratio >= 65:
            tone = "긍정 우세"
        elif ratio >= 45:
            tone = "혼조"
        elif ratio >= 30:
            tone = "부정 우세"
        else:
            tone = "경계"

    return {
        "tone": tone,
        "positive": pos_count,
        "negative": neg_count,
        "ratio": ratio,
        "pos_examples": pos_examples,
        "neg_examples": neg_examples,
    }


def _extract_key_figures(content: str) -> List[str]:
    """Extract clean numeric data points (prices, index levels, percentages) from content."""
    figures: List[str] = []
    seen: set[str] = set()

    def _add(fig: str) -> None:
        key = re.sub(r"[^\w%.]", "", fig.lower())
        if key not in seen and len(fig) > 5:
            seen.add(key)
            figures.append(fig)

    # Market indices with percentage: "KOSPI 6,244.13(-1.00%)"
    for m in re.finditer(
        r"((?:KOSPI|KOSDAQ|S&P|나스닥|다우|USD/KRW|EUR/USD|BTC|ETH)"
        r"\s*[\d,.]+\s*\([+-]?[\d.]+%\))",
        content,
    ):
        _add(m.group(1).strip())

    # Named prices: "비트코인 83,200 달러" — require currency right after number
    for m in re.finditer(
        r"((?:비트코인|BTC|이더리움|ETH|KOSPI|KOSDAQ|S&P|나스닥|다우)"
        r"\s+[\d,.]+\s*(?:달러|원|포인트|pt))",
        content,
    ):
        _add(m.group(1).strip())

    # Explicit percentage changes: "전일 대비 +2.3%"
    for m in re.finditer(
        r"((?:전일|전주|전월|YoY|MoM|QoQ)\s*대비\s*[+-]?[\d.]+\s*%)",
        content,
    ):
        _add(m.group(1).strip())

    return figures[:5]


def _find_shared_topics_across_categories(
    summaries: List[Optional[Dict[str, Any]]],
) -> List[Tuple[str, int, List[str]]]:
    """Find topics that appear across multiple categories, returning (topic, category_count, categories)."""
    topic_defs = _cross_asset_topics()
    # Map: topic -> list of category names that mention it
    topic_presence: Dict[str, List[str]] = {t: [] for t in topic_defs}
    category_labels = {
        "crypto": "암호화폐",
        "stock": "주식",
        "regulatory": "규제",
        "social": "소셜",
        "worldmonitor": "월드모니터",
        "political": "정치인 거래",
        "market": "시장",
        "security": "보안",
    }

    for s in summaries:
        if not s or not s.get("content"):
            continue
        stype = s.get("type", "")
        label = category_labels.get(stype, stype)
        text = (s.get("content", "") + " " + " ".join(s.get("highlights", []) or [])).lower()
        for topic, keywords in topic_defs.items():
            for kw in keywords:
                if kw.lower() in text:
                    if label not in topic_presence[topic]:
                        topic_presence[topic].append(label)
                    break

    # Only topics mentioned in 2+ categories are cross-cutting
    cross_topics = [(topic, len(cats), cats) for topic, cats in topic_presence.items() if len(cats) >= 2]
    cross_topics.sort(key=lambda x: x[1], reverse=True)
    return cross_topics


def _extract_category_data_points(summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract structured data points from a category summary for richer output."""
    if not summary or not summary.get("content"):
        return {"titles": [], "figures": [], "theme_names": [], "count": 0}

    content = summary["content"]
    count = summary.get("count", 0)

    # Extract top titles (first 5 meaningful ones)
    titles: List[str] = []
    for m in re.finditer(r"(?<!!)\[([^\]]{10,})\]\(([^)]+)\)", content):
        title = m.group(1).strip()
        url = m.group(2)
        # Skip image file links (e.g. .png, .jpg, assets/images paths)
        if re.search(r"\.(png|jpg|jpeg|gif|svg|webp)", url, re.IGNORECASE):
            continue
        if _is_noise_title(title):
            continue
        if title not in titles:
            titles.append(title)
        if len(titles) >= 5:
            break

    # Numeric figures
    figures = _extract_key_figures(content)

    # Theme names from crypto themes
    theme_names = [t[0] for t in (summary.get("themes") or [])]

    return {
        "titles": titles,
        "figures": figures,
        "theme_names": theme_names,
        "count": count,
    }


def _topic_hits(summary: Optional[Dict[str, Any]]) -> Dict[str, int]:
    if not summary:
        return {}
    text = "\n".join(
        [
            summary.get("title", ""),
            summary.get("content", ""),
            " ".join(summary.get("highlights", []) or []),
            " ".join(summary.get("key_summary", []) or []),
        ]
    ).lower()
    hits: Dict[str, int] = {}
    for topic, keywords in _cross_asset_topics().items():
        score = 0
        matched_keywords: List[str] = []
        for kw in keywords:
            cnt = text.count(kw.lower())
            if cnt > 0:
                score += cnt
                matched_keywords.append(kw)
        hits[topic] = score
    return hits


def _relation_rows(
    summaries: Dict[str, Optional[Dict[str, Any]]],
) -> List[Tuple[str, str, int, str]]:
    rows: List[Tuple[str, str, int, str]] = []
    pairs = [
        ("암호화폐", "주식", "crypto", "stock"),
        ("암호화폐", "정치인 거래", "crypto", "political"),
        ("주식", "정치인 거래", "stock", "political"),
        ("암호화폐", "규제", "crypto", "regulatory"),
        ("주식", "규제", "stock", "regulatory"),
        ("암호화폐", "소셜", "crypto", "social"),
        ("월드모니터", "암호화폐", "worldmonitor", "crypto"),
        ("월드모니터", "주식", "worldmonitor", "stock"),
    ]
    topic_keys = list(_cross_asset_topics().keys())
    hit_maps = {k: _topic_hits(v) for k, v in summaries.items()}

    # Diagnostic templates by topic
    diagnostics = {
        "금리/유동성": "금리/유동성 이슈가 양쪽 자산에 동시 영향",
        "환율/달러": "달러·환율 변동이 교차 자산 민감도 확대",
        "정책/규제": "정책·규제 이벤트가 복수 시장에 파급",
        "리스크 이벤트": "리스크 이벤트(해킹/청산 등) 동시 노출",
        "수급/심리": "수급·심리 키워드 동반 급증 → 변동성 주의",
        "실적/지표": "매크로 지표 발표가 연쇄 반응 유발 가능",
        "기술/온체인": "온체인·기술 이슈가 시장 전반에 확산",
        "지정학": "지정학 리스크가 안전자산·위험자산 동시 압박",
    }

    for left_name, right_name, left_key, right_key in pairs:
        left = hit_maps.get(left_key, {})
        right = hit_maps.get(right_key, {})
        if not left or not right:
            continue
        shared_topics: List[Tuple[str, int]] = []
        for t in topic_keys:
            if left.get(t, 0) > 0 and right.get(t, 0) > 0:
                shared_topics.append((t, min(left[t], right[t])))
        shared_topics.sort(key=lambda x: x[1], reverse=True)
        if not shared_topics:
            rows.append((left_name, right_name, 0, "낮음 — 공통 이슈 미감지"))
            continue
        score = sum(v for _, v in shared_topics[:3])
        top_topic = shared_topics[0][0]
        diag = diagnostics.get(top_topic, f"{top_topic} 관련 공통 신호 감지")
        if score >= 20:
            level = "높음"
        elif score >= 12:
            level = "중간"
        else:
            level = "낮음"
        rows.append((left_name, right_name, score, f"{level} — {diag}"))
    return rows


def _coverage_warnings(summaries: Dict[str, Optional[Dict[str, Any]]]) -> List[str]:
    warnings = []
    if not summaries.get("crypto"):
        warnings.append("- 암호화폐 일일 리포트가 없어 코인-주식 연계 분석 정밀도가 낮습니다.")
    if not summaries.get("stock"):
        warnings.append("- 주식 일일 리포트가 없어 교차자산 수급 비교가 제한됩니다.")
    if not summaries.get("market"):
        warnings.append("- 시장 종합 리포트가 없어 매크로(금리/환율) 연결 해석이 제한됩니다.")
    if not summaries.get("worldmonitor"):
        warnings.append("- 월드모니터 브리핑이 없어 글로벌 지정학/에너지 리스크 연결 분석이 제한됩니다.")
    if not summaries.get("political") and not summaries.get("regulatory"):
        warnings.append("- 정책/규제 데이터가 부족해 이벤트 기반 리스크 점검이 약합니다.")
    return warnings


def _render_generated_image(filename: str, alt: str) -> Optional[str]:
    image_path = os.path.join(POSTS_DIR, "..", "assets", "images", "generated", filename)
    if not os.path.exists(image_path):
        return None
    return f"![{alt}]({{{{ '/assets/images/generated/{filename}' | relative_url }}}})"
