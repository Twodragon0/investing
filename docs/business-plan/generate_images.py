"""사업계획서용 시각화 이미지 생성 스크립트."""

import os

import matplotlib
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")

# Korean font setup
plt.rcParams["font.family"] = "Nanum Gothic"
plt.rcParams["axes.unicode_minus"] = False

OUT = os.path.join(os.path.dirname(__file__), "images")
os.makedirs(OUT, exist_ok=True)

# Color palette
DARK_BG = "#0f1419"
CARD_BG = "#1a1f2e"
ACCENT_BLUE = "#4fc3f7"
ACCENT_GREEN = "#66bb6a"
ACCENT_RED = "#ef5350"
ACCENT_ORANGE = "#ffa726"
ACCENT_PURPLE = "#ab47bc"
ACCENT_CYAN = "#26c6da"
TEXT_WHITE = "#e8eaed"
TEXT_GRAY = "#9aa0a6"
GRID_COLOR = "#2a3040"


def fig_dark(figsize=(14, 8)):
    fig, ax = plt.subplots(figsize=figsize, facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG)
    return fig, ax


# ──────────────────────────────────────────────────────────────
# 1. 백테스트 성과 비교 (Strategy vs Buy & Hold)
# ──────────────────────────────────────────────────────────────
def gen_backtest_comparison():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7), facecolor=DARK_BG)

    # Left: Returns comparison bar chart
    ax1.set_facecolor(DARK_BG)
    categories = ["총 수익률", "최대 낙폭\n(MDD)", "초과수익\n(Alpha)"]
    strategy = [0.12, -6.93, 25.50]
    buyhold = [-25.38, -63.58, 0]
    x = np.arange(len(categories))
    w = 0.35

    bars1 = ax1.bar(x - w / 2, strategy, w, label="ATS 3.0 전략", color=ACCENT_GREEN, alpha=0.9, edgecolor="none")
    bars2 = ax1.bar(x + w / 2, buyhold, w, label="단순 보유 (B&H)", color=ACCENT_RED, alpha=0.7, edgecolor="none")

    for bar, val in zip(bars1, strategy, strict=True):
        ypos = bar.get_height() + 1 if val >= 0 else bar.get_height() - 3
        ax1.text(bar.get_x() + bar.get_width() / 2, ypos, f"{val:+.1f}%", ha="center", va="bottom", color=TEXT_WHITE, fontsize=13, fontweight="bold")
    for bar, val in zip(bars2, buyhold, strict=True):
        if val != 0:
            ypos = bar.get_height() - 3
            ax1.text(bar.get_x() + bar.get_width() / 2, ypos, f"{val:+.1f}%", ha="center", va="top", color=TEXT_WHITE, fontsize=13, fontweight="bold")

    ax1.set_xticks(x)
    ax1.set_xticklabels(categories, color=TEXT_WHITE, fontsize=13)
    ax1.set_ylabel("수익률 (%)", color=TEXT_WHITE, fontsize=13)
    ax1.tick_params(colors=TEXT_WHITE)
    ax1.spines["bottom"].set_color(GRID_COLOR)
    ax1.spines["left"].set_color(GRID_COLOR)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.axhline(y=0, color=GRID_COLOR, linewidth=0.8)
    ax1.legend(loc="upper right", facecolor=CARD_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_WHITE, fontsize=11)
    ax1.set_title("수익률 비교 (1년 백테스트)", color=TEXT_WHITE, fontsize=15, fontweight="bold", pad=15)

    # Right: Risk metrics radar-style comparison
    ax2.set_facecolor(DARK_BG)
    metrics = ["Sharpe\nRatio", "Sortino\nRatio", "Omega\nRatio", "승률\n(%)", "Profit\nFactor"]
    values = [0.81, 1.62, 1.66, 45.76, 1.01]
    colors = [ACCENT_BLUE, ACCENT_GREEN, ACCENT_CYAN, ACCENT_ORANGE, ACCENT_PURPLE]

    bars = ax2.bar(metrics, values, color=colors, alpha=0.85, edgecolor="none", width=0.6)
    for bar, val in zip(bars, values, strict=True):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05, f"{val:.2f}", ha="center", va="bottom", color=TEXT_WHITE, fontsize=13, fontweight="bold")

    ax2.set_ylabel("값", color=TEXT_WHITE, fontsize=13)
    ax2.tick_params(colors=TEXT_WHITE)
    ax2.set_xticks(range(len(metrics)))
    ax2.set_xticklabels(metrics, color=TEXT_WHITE, fontsize=11)
    ax2.spines["bottom"].set_color(GRID_COLOR)
    ax2.spines["left"].set_color(GRID_COLOR)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.set_title("리스크 대비 성과 지표", color=TEXT_WHITE, fontsize=15, fontweight="bold", pad=15)

    fig.suptitle("ATS 3.0 백테스트 성과 (2025.03 ~ 2026.03)", color=ACCENT_BLUE, fontsize=18, fontweight="bold", y=0.98)
    plt.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(os.path.join(OUT, "01_backtest_performance.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print("  [1/6] 백테스트 성과 비교")


# ──────────────────────────────────────────────────────────────
# 2. 시장 규모 (TAM/SAM/SOM)
# ──────────────────────────────────────────────────────────────
def gen_market_size():
    fig, ax = fig_dark((12, 8))

    # Concentric circles for TAM > SAM > SOM
    circles = [
        (3.5, "TAM\n글로벌 암호화폐 거래 플랫폼\n$18.4B (2026)", ACCENT_BLUE, 0.15),
        (2.5, "SAM\n아시아 퀀트 트레이딩 SaaS\n$2.1B", ACCENT_GREEN, 0.2),
        (1.5, "SOM\n한국 개인/소형 펀드 구독\n$120M (1차 목표)", ACCENT_ORANGE, 0.3),
    ]

    for radius, label, color, alpha in circles:
        circle = plt.Circle((0.5, 0.5), radius / 7, transform=ax.transAxes, color=color, alpha=alpha, linewidth=2, edgecolor=color)
        ax.add_patch(circle)
        # Position label
        y_offset = radius / 7
        ax.text(0.5, 0.5 + y_offset - 0.08, label, transform=ax.transAxes, ha="center", va="center", color=TEXT_WHITE, fontsize=12 if radius > 2 else 11, fontweight="bold", linespacing=1.6)

    # Side annotations
    annotations = [
        (0.82, 0.85, "CAGR 11.1%\n(2024-2030)", ACCENT_BLUE),
        (0.82, 0.65, "아시아 퀀트 트레이딩\n연 23% 성장", ACCENT_GREEN),
        (0.82, 0.45, "한국 암호화폐 투자자\n600만 명+", ACCENT_ORANGE),
    ]
    for x, y, text, color in annotations:
        ax.text(x, y, text, transform=ax.transAxes, ha="left", va="center", color=color, fontsize=11, fontweight="bold", linespacing=1.5,
                bbox=dict(boxstyle="round,pad=0.5", facecolor=CARD_BG, edgecolor=color, alpha=0.8))

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title("시장 규모 분석 (TAM / SAM / SOM)", color=TEXT_WHITE, fontsize=18, fontweight="bold", pad=20)

    fig.savefig(os.path.join(OUT, "02_market_size.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print("  [2/6] 시장 규모")


# ──────────────────────────────────────────────────────────────
# 3. 수익 모델 & 매출 전망
# ──────────────────────────────────────────────────────────────
def gen_revenue_projection():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7), facecolor=DARK_BG, gridspec_kw={"width_ratios": [1.2, 1]})

    # Left: Revenue projection
    ax1.set_facecolor(DARK_BG)
    quarters = ["Q3\n2026", "Q4\n2026", "Q1\n2027", "Q2\n2027", "Q3\n2027", "Q4\n2027"]
    b2c = [5, 12, 22, 35, 50, 65]  # B2C 구독 (백만원)
    b2b = [0, 0, 5, 15, 30, 55]  # B2B API SaaS
    total = [a + b for a, b in zip(b2c, b2b, strict=True)]

    ax1.fill_between(range(len(quarters)), b2c, alpha=0.3, color=ACCENT_GREEN)
    ax1.fill_between(range(len(quarters)), b2c, total, alpha=0.3, color=ACCENT_BLUE)
    ax1.plot(range(len(quarters)), b2c, "o-", color=ACCENT_GREEN, linewidth=2.5, markersize=8, label="B2C 구독")
    ax1.plot(range(len(quarters)), total, "s-", color=ACCENT_BLUE, linewidth=2.5, markersize=8, label="B2C + B2B")

    for i, (_c, t) in enumerate(zip(b2c, total, strict=True)):
        ax1.text(i, t + 3, f"{t}M", ha="center", color=TEXT_WHITE, fontsize=11, fontweight="bold")

    ax1.set_xticks(range(len(quarters)))
    ax1.set_xticklabels(quarters, color=TEXT_WHITE, fontsize=11)
    ax1.set_ylabel("매출 (백만원)", color=TEXT_WHITE, fontsize=13)
    ax1.tick_params(colors=TEXT_WHITE)
    ax1.spines["bottom"].set_color(GRID_COLOR)
    ax1.spines["left"].set_color(GRID_COLOR)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.legend(loc="upper left", facecolor=CARD_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_WHITE, fontsize=11)
    ax1.set_title("분기별 매출 전망", color=TEXT_WHITE, fontsize=15, fontweight="bold", pad=15)
    ax1.grid(axis="y", color=GRID_COLOR, alpha=0.5)

    # Right: Revenue model breakdown
    ax2.set_facecolor(DARK_BG)
    models = ["B2C 구독\n(개인 투자자)", "B2B API\n(핀테크/펀드)", "프리미엄\n(기관 라이선스)"]
    price_labels = ["29,900원/월", "99만원/월", "500만원/월"]
    colors = [ACCENT_GREEN, ACCENT_BLUE, ACCENT_PURPLE]

    bars = ax2.barh(models, [30, 45, 25], color=colors, alpha=0.8, edgecolor="none", height=0.5)
    for bar, label in zip(bars, price_labels, strict=True):
        ax2.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2, label, va="center", color=TEXT_WHITE, fontsize=12, fontweight="bold")

    ax2.set_xlabel("매출 비중 (%)", color=TEXT_WHITE, fontsize=13)
    ax2.set_xlim(0, 60)
    ax2.tick_params(colors=TEXT_WHITE)
    ax2.set_yticks(range(len(models)))
    ax2.set_yticklabels(models, color=TEXT_WHITE, fontsize=12)
    ax2.spines["bottom"].set_color(GRID_COLOR)
    ax2.spines["left"].set_color(GRID_COLOR)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.set_title("수익 모델 구성", color=TEXT_WHITE, fontsize=15, fontweight="bold", pad=15)

    fig.suptitle("DragonQuant 수익 모델 & 매출 전망", color=ACCENT_BLUE, fontsize=18, fontweight="bold", y=0.98)
    plt.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(os.path.join(OUT, "03_revenue_projection.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print("  [3/6] 수익 모델 & 매출 전망")


# ──────────────────────────────────────────────────────────────
# 4. 플랫폼 아키텍처 다이어그램
# ──────────────────────────────────────────────────────────────
def gen_architecture():
    fig, ax = fig_dark((16, 9))
    ax.axis("off")

    def draw_box(x, y, w, h, label, color, sublabel="", fontsize=11):
        rect = mpatches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02", facecolor=color, alpha=0.25, edgecolor=color, linewidth=2)
        ax.add_patch(rect)
        ax.text(x + w / 2, y + h / 2 + (0.01 if sublabel else 0), label, ha="center", va="center", color=TEXT_WHITE, fontsize=fontsize, fontweight="bold")
        if sublabel:
            ax.text(x + w / 2, y + h / 2 - 0.03, sublabel, ha="center", va="center", color=TEXT_GRAY, fontsize=9)

    def draw_arrow(x1, y1, x2, y2, color=TEXT_GRAY):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", color=color, lw=2))

    # Title
    ax.text(0.5, 0.95, "DragonQuant Platform Architecture", ha="center", va="center", color=ACCENT_BLUE, fontsize=20, fontweight="bold")

    # Layer labels
    ax.text(0.02, 0.85, "Data\nSources", ha="center", va="center", color=TEXT_GRAY, fontsize=10, fontstyle="italic")
    ax.text(0.02, 0.62, "investing\nrepo", ha="center", va="center", color=ACCENT_GREEN, fontsize=10, fontweight="bold")
    ax.text(0.02, 0.38, "crypto\nrepo", ha="center", va="center", color=ACCENT_BLUE, fontsize=10, fontweight="bold")
    ax.text(0.02, 0.12, "Output", ha="center", va="center", color=TEXT_GRAY, fontsize=10, fontstyle="italic")

    # Data Sources (top row)
    sources = [
        (0.08, "CryptoPanic\nNewsAPI"),
        (0.22, "SEC\nFRED"),
        (0.36, "CoinGecko\nCMC"),
        (0.50, "Telegram\nTwitter/X"),
        (0.64, "DeFi Llama\nBlockchain"),
        (0.78, "Google News\nRSS Feeds"),
    ]
    for x, label in sources:
        draw_box(x, 0.80, 0.12, 0.08, label, ACCENT_ORANGE, fontsize=9)

    # investing repo (middle-upper)
    draw_box(0.08, 0.53, 0.25, 0.14, "8 Collectors\n수집 + 중복 제거", ACCENT_GREEN, "SHA256 + Fuzzy >80%")
    draw_box(0.38, 0.53, 0.25, 0.14, "3 Generators\n요약 + 이미지 생성", ACCENT_GREEN, "Daily/Weekly/Market")
    draw_box(0.68, 0.53, 0.25, 0.14, "Jekyll Site\n9 Categories", ACCENT_GREEN, "investing.2twodragon.com")

    # Arrows: sources -> collectors
    for x, _ in sources:
        draw_arrow(x + 0.06, 0.80, 0.20, 0.67, ACCENT_ORANGE)
    # Arrows: collectors -> generators -> site
    draw_arrow(0.33, 0.60, 0.38, 0.60, ACCENT_GREEN)
    draw_arrow(0.63, 0.60, 0.68, 0.60, ACCENT_GREEN)

    # _posts connection
    ax.text(0.50, 0.48, "_posts/*.md  (구조화된 시장 데이터)", ha="center", va="center", color=ACCENT_CYAN, fontsize=11, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", facecolor=CARD_BG, edgecolor=ACCENT_CYAN, linewidth=2))
    draw_arrow(0.50, 0.53, 0.50, 0.50, ACCENT_CYAN)
    draw_arrow(0.50, 0.46, 0.50, 0.42, ACCENT_CYAN)

    # crypto repo (middle-lower)
    draw_box(0.08, 0.25, 0.20, 0.14, "Market Intelligence\n14 Components", ACCENT_BLUE, "가중치 합계 1.0")
    draw_box(0.32, 0.25, 0.20, 0.14, "Signal Synthesis\nTA + MI Blend", ACCENT_BLUE, "6 Indicators + MI")
    draw_box(0.56, 0.25, 0.20, 0.14, "Risk Engine\nKelly + CVaR", ACCENT_BLUE, "MDD 20% Circuit Breaker")
    draw_box(0.80, 0.25, 0.13, 0.14, "Backtest\n& Verify", ACCENT_PURPLE, "Monte Carlo")

    # Arrows within crypto
    draw_arrow(0.28, 0.32, 0.32, 0.32, ACCENT_BLUE)
    draw_arrow(0.52, 0.32, 0.56, 0.32, ACCENT_BLUE)
    draw_arrow(0.76, 0.32, 0.80, 0.32, ACCENT_PURPLE)

    # Output (bottom row)
    draw_box(0.08, 0.04, 0.20, 0.10, "Upbit / Bithumb\n자동매매", ACCENT_GREEN, "Paper / Live")
    draw_box(0.32, 0.04, 0.20, 0.10, "FastAPI Dashboard\nWebSocket 실시간", ACCENT_BLUE, "REST API + WS")
    draw_box(0.56, 0.04, 0.20, 0.10, "Slack 4-Channel\n보안 알림", ACCENT_ORANGE, "CRITICAL/HIGH/MED/INFO")
    draw_box(0.80, 0.04, 0.13, 0.10, "B2C/B2B\nSaaS API", ACCENT_PURPLE)

    # Arrows: crypto -> output
    draw_arrow(0.18, 0.25, 0.18, 0.14, TEXT_GRAY)
    draw_arrow(0.42, 0.25, 0.42, 0.14, TEXT_GRAY)
    draw_arrow(0.66, 0.25, 0.66, 0.14, TEXT_GRAY)

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.savefig(os.path.join(OUT, "04_platform_architecture.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print("  [4/6] 플랫폼 아키텍처")


# ──────────────────────────────────────────────────────────────
# 5. 리스크 관리 비교 (MDD 시뮬레이션)
# ──────────────────────────────────────────────────────────────
def gen_risk_comparison():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7), facecolor=DARK_BG)

    # Left: MDD comparison (simulated drawdown curves)
    ax1.set_facecolor(DARK_BG)
    np.random.seed(42)
    days = 365
    t = np.arange(days)

    # Simulate buy & hold drawdown (deep)
    bh_returns = np.random.normal(-0.001, 0.025, days)
    bh_cumulative = np.cumprod(1 + bh_returns) * 100
    bh_peak = np.maximum.accumulate(bh_cumulative)
    bh_dd = (bh_cumulative - bh_peak) / bh_peak * 100

    # Simulate strategy drawdown (shallow, controlled)
    st_returns = np.random.normal(0.0003, 0.008, days)
    st_cumulative = np.cumprod(1 + st_returns) * 100
    st_peak = np.maximum.accumulate(st_cumulative)
    st_dd = (st_cumulative - st_peak) / st_peak * 100

    ax1.fill_between(t, bh_dd, 0, alpha=0.3, color=ACCENT_RED)
    ax1.fill_between(t, st_dd, 0, alpha=0.3, color=ACCENT_GREEN)
    ax1.plot(t, bh_dd, color=ACCENT_RED, linewidth=1.5, label=f"Buy & Hold (MDD: {bh_dd.min():.1f}%)", alpha=0.8)
    ax1.plot(t, st_dd, color=ACCENT_GREEN, linewidth=1.5, label=f"ATS 3.0 (MDD: {st_dd.min():.1f}%)", alpha=0.8)
    ax1.axhline(y=-20, color=ACCENT_ORANGE, linewidth=1.5, linestyle="--", alpha=0.7, label="Circuit Breaker (-20%)")

    ax1.set_xlabel("거래일", color=TEXT_WHITE, fontsize=12)
    ax1.set_ylabel("Drawdown (%)", color=TEXT_WHITE, fontsize=12)
    ax1.tick_params(colors=TEXT_WHITE)
    ax1.spines["bottom"].set_color(GRID_COLOR)
    ax1.spines["left"].set_color(GRID_COLOR)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.legend(loc="lower left", facecolor=CARD_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_WHITE, fontsize=10)
    ax1.set_title("최대 낙폭 (MDD) 비교", color=TEXT_WHITE, fontsize=15, fontweight="bold", pad=15)
    ax1.grid(axis="y", color=GRID_COLOR, alpha=0.3)

    # Right: CVaR tail risk visualization
    ax2.set_facecolor(DARK_BG)
    returns = np.concatenate([np.random.normal(0.003, 0.02, 1800), np.random.normal(-0.05, 0.03, 200)])
    np.random.shuffle(returns)

    ax2.hist(returns * 100, bins=60, color=ACCENT_BLUE, alpha=0.6, edgecolor="none", density=True)
    var_95 = np.percentile(returns * 100, 5)
    cvar_95 = returns[returns * 100 <= var_95].mean() * 100

    ax2.axvline(x=var_95, color=ACCENT_ORANGE, linewidth=2, linestyle="--", label=f"VaR (95%): {var_95:.2f}%")
    ax2.axvline(x=cvar_95, color=ACCENT_RED, linewidth=2, linestyle="-", label=f"CVaR: {cvar_95:.2f}%")

    # Shade tail
    hist_vals, bin_edges = np.histogram(returns * 100, bins=60, density=True)
    for i in range(len(bin_edges) - 1):
        if bin_edges[i + 1] <= var_95:
            ax2.fill_between([bin_edges[i], bin_edges[i + 1]], 0, hist_vals[i], color=ACCENT_RED, alpha=0.4)

    ax2.set_xlabel("일일 수익률 (%)", color=TEXT_WHITE, fontsize=12)
    ax2.set_ylabel("밀도", color=TEXT_WHITE, fontsize=12)
    ax2.tick_params(colors=TEXT_WHITE)
    ax2.spines["bottom"].set_color(GRID_COLOR)
    ax2.spines["left"].set_color(GRID_COLOR)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.legend(loc="upper left", facecolor=CARD_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_WHITE, fontsize=10)
    ax2.set_title("꼬리 위험 분석 (CVaR)", color=TEXT_WHITE, fontsize=15, fontweight="bold", pad=15)

    fig.suptitle("리스크 관리 시스템", color=ACCENT_BLUE, fontsize=18, fontweight="bold", y=0.98)
    plt.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(os.path.join(OUT, "05_risk_management.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print("  [5/6] 리스크 관리")


# ──────────────────────────────────────────────────────────────
# 6. 자금 운용 계획
# ──────────────────────────────────────────────────────────────
def gen_fund_allocation():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7), facecolor=DARK_BG)

    # Left: Pie chart - fund allocation
    ax1.set_facecolor(DARK_BG)
    labels = ["클라우드 인프라\n(AWS/GCP)", "데이터 API\n구독", "인건비\n(외주 개발)", "마케팅\n& 사업개발", "운영비\n& 예비"]
    sizes = [35, 15, 25, 15, 10]
    colors = [ACCENT_BLUE, ACCENT_GREEN, ACCENT_ORANGE, ACCENT_PURPLE, ACCENT_CYAN]
    explode = (0.05, 0, 0, 0, 0)

    wedges, texts, autotexts = ax1.pie(sizes, labels=labels, colors=colors, autopct="%1.0f%%", startangle=90,
                                        explode=explode, pctdistance=0.75, textprops={"color": TEXT_WHITE, "fontsize": 11})
    for t in autotexts:
        t.set_fontweight("bold")
        t.set_fontsize(13)

    ax1.set_title("자금 운용 계획 (5,000만원)", color=TEXT_WHITE, fontsize=15, fontweight="bold", pad=15)

    # Right: Timeline / Milestone
    ax2.set_facecolor(DARK_BG)
    ax2.axis("off")

    milestones = [
        ("2026 Q3", "MVP 출시", "Paper Trading B2C\n암호화폐 Top 5", ACCENT_GREEN),
        ("2026 Q4", "유료 전환", "실매매 구독 모델\n첫 유료 고객 확보", ACCENT_BLUE),
        ("2027 Q1", "B2B 확장", "API SaaS 출시\n핀테크 파트너십", ACCENT_ORANGE),
        ("2027 Q2", "주식 확장", "국내외 주식 시장\n멀티 에셋 대응", ACCENT_PURPLE),
    ]

    for i, (date, title, desc, color) in enumerate(milestones):
        y = 0.85 - i * 0.22
        # Timeline dot and line
        ax2.plot(0.08, y, "o", color=color, markersize=16, zorder=5)
        if i < len(milestones) - 1:
            ax2.plot([0.08, 0.08], [y - 0.02, y - 0.20], "-", color=GRID_COLOR, linewidth=2, zorder=1)
        # Text
        ax2.text(0.15, y + 0.02, date, color=color, fontsize=13, fontweight="bold", va="center")
        ax2.text(0.30, y + 0.02, title, color=TEXT_WHITE, fontsize=14, fontweight="bold", va="center")
        ax2.text(0.30, y - 0.05, desc, color=TEXT_GRAY, fontsize=10, va="center", linespacing=1.5)

    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.set_title("사업화 로드맵", color=TEXT_WHITE, fontsize=15, fontweight="bold", pad=15)

    fig.suptitle("예비창업패키지 자금 운용 & 로드맵", color=ACCENT_BLUE, fontsize=18, fontweight="bold", y=0.98)
    plt.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(os.path.join(OUT, "06_fund_roadmap.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print("  [6/6] 자금 운용 & 로드맵")


if __name__ == "__main__":
    print("사업계획서 이미지 생성 중...")
    gen_backtest_comparison()
    gen_market_size()
    gen_revenue_projection()
    gen_architecture()
    gen_risk_comparison()
    gen_fund_allocation()
    print(f"\n완료! 이미지 저장 위치: {OUT}/")
