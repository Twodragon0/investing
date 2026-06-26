"""generate_og_images / og_visuals 공유 렌더링 프리미티브.

`generate_og_images.py` 에서 추출(2026-06-26). 다크 finance 테마 색상 + matplotlib
백엔드/폰트 셋업 + 폰트 kwargs(`_FK`)를 한 곳에 모아, 메인 모듈과 [[og_visuals]]
드로잉 모듈이 순환 import 없이 동일한 렌더링 상태를 공유한다. import 시점에 CJK
폰트를 1회 등록(matplotlib rcParams 전역)한다.
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("og-image-gen")

# ── 다크 finance 테마 색상 (image_generator/base.py 와 정렬) ──
BG_COLOR = "#0d1117"
TEXT_WHITE = "#e6edf3"
TEXT_GRAY = "#9da5ae"
TEXT_MUTED = "#6b7280"
DIVIDER_COLOR = "#30363d"

# ── matplotlib setup ──
_MPL_AVAILABLE = False
matplotlib: Any = None
fm: Any = None
mpatches: Any = None
plt: Any = None
try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.patches as mpatches  # noqa: F401  (재-export)
    import matplotlib.pyplot as plt  # noqa: F401  (재-export)

    _MPL_AVAILABLE = True
except ImportError:
    logger.error("matplotlib is required but not installed")

# ── Font setup (same candidates as image_generator.py) ──
_FONT_FAMILY = "monospace"
_FONT_BOLD_PATH: Optional[str] = None


def _discover_cjk_fonts() -> List[str]:
    """Return CJK font paths: static candidates + dynamic discovery."""
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    ]
    # Dynamic discovery for Ubuntu 24.04+ where paths may differ
    import glob as _gl
    import subprocess

    for pattern in [
        "/usr/share/fonts/**/NotoSansCJK*.*",
        "/usr/share/fonts/**/NotoSans*KR*.*",
        "/usr/share/fonts/**/Noto*CJK*.*",
    ]:
        candidates.extend(_gl.glob(pattern, recursive=True))
    # fc-list fallback
    try:
        _result = subprocess.run(
            ["fc-list", ":lang=ko", "-f", "%{file}\n"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for _line in _result.stdout.strip().split("\n"):
            if _line and os.path.exists(_line):
                candidates.append(_line)
    except Exception as exc:
        logger.debug("fc-list fallback failed: %s", exc)
    # deduplicate while preserving order
    seen: set = set()
    unique: List[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


if _MPL_AVAILABLE:
    _korean_font_candidates = _discover_cjk_fonts()
    for _fp in _korean_font_candidates:
        if os.path.exists(_fp):
            fm.fontManager.addfont(_fp)
            _prop = fm.FontProperties(fname=_fp)
            _FONT_FAMILY = _prop.get_name()
            _FONT_BOLD_PATH = _fp
            logger.info("Using font '%s' for CJK support", _FONT_FAMILY)
            break
    else:
        logger.warning("No CJK font found, Korean text may not render correctly")

    matplotlib.rcParams["font.family"] = [_FONT_FAMILY]
    matplotlib.rcParams["text.parse_math"] = False

_FK: Dict[str, Any] = {"fontfamily": _FONT_FAMILY} if _MPL_AVAILABLE else {}
