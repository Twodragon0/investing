"""수집기 공통 기반 클래스 (BaseCollector).

모든 뉴스 수집기가 공유하는 초기화, 중복 제거, 포스트 생성,
메트릭 로깅 로직을 추상화합니다.

사용법::

    class CryptoNewsCollector(BaseCollector):
        name = "crypto_news"
        category = "crypto-news"
        state_file = "crypto_news_seen.json"

        def fetch(self) -> list[dict]:
            ...

        def process(self, items: list[dict]) -> list[dict]:
            ...

        def build_content(self, items: list[dict]) -> str:
            ...
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from datetime import datetime

from common.collector_config import get_collector_config
from common.collector_metrics import log_collection_summary
from common.config import get_kst_now, get_verify_ssl, setup_logging
from common.dedup import DedupEngine, deduplicate_by_url
from common.post_generator import PostGenerator

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """수집기 공통 기반 클래스.

    서브클래스는 ``name``, ``category``, ``state_file`` 클래스 변수를
    반드시 설정하고, ``fetch``, ``process``, ``build_content`` 메서드를
    구현해야 합니다.
    """

    # 서브클래스에서 반드시 설정
    name: str = ""
    """수집기 이름 (예: ``"crypto_news"``)."""

    category: str = ""
    """포스트 카테고리 (예: ``"crypto-news"``)."""

    state_file: str = ""
    """``_state/`` 디렉토리 내 중복 방지 상태 파일명."""

    max_age_days: int = 30
    """DedupEngine 상태 보존 기간 (일)."""

    def __init__(self) -> None:
        if not self.name:
            raise ValueError("서브클래스에서 'name' 클래스 변수를 설정하세요.")
        if not self.category:
            raise ValueError("서브클래스에서 'category' 클래스 변수를 설정하세요.")
        if not self.state_file:
            raise ValueError("서브클래스에서 'state_file' 클래스 변수를 설정하세요.")

        self.logger = setup_logging(f"collect_{self.name}")
        self.verify_ssl = get_verify_ssl()
        self.config = get_collector_config(self.name)
        self.dedup = DedupEngine(self.state_file, max_age_days=self.max_age_days)
        self.post_gen = PostGenerator(self.category)
        self.now: datetime = get_kst_now()
        self.today: str = self.now.strftime("%Y-%m-%d")
        self._started_at: float = 0.0
        self._created_count: int = 0

    # ── 추상 메서드 ──

    @abstractmethod
    def fetch(self) -> List[Dict[str, Any]]:
        """데이터 소스에서 뉴스 항목을 가져옵니다."""

    @abstractmethod
    def process(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """가져온 항목을 정제·필터링합니다."""

    @abstractmethod
    def build_content(self, items: List[Dict[str, Any]]) -> str:
        """마크다운 포스트 본문을 생성합니다."""

    # ── 공통 메서드 ──

    def deduplicate(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """URL 기반 인세션 중복 제거를 수행합니다."""
        return deduplicate_by_url(items)

    def is_duplicate(self, title: str, source: str, url: str = "") -> bool:
        """DedupEngine을 통해 크로스 세션 중복 여부를 확인합니다."""
        return self.dedup.is_duplicate(title, source, self.today, url)

    def is_duplicate_exact(self, title: str, source: str) -> bool:
        """DedupEngine 해시 기반 정확 중복 여부를 확인합니다."""
        return self.dedup.is_duplicate_exact(title, source, self.today)

    def mark_seen(self, title: str, source: str) -> None:
        """항목을 중복 방지 상태에 기록합니다."""
        self.dedup.mark_seen(title, source, self.today)

    def create_post(
        self,
        title: str,
        content: str,
        *,
        tags: Optional[List[str]] = None,
        source: str = "",
        lang: str = "ko",
        image: str = "",
        extra_frontmatter: Optional[Dict[str, str]] = None,
        slug: Optional[str] = None,
        logical_date: Optional[str] = None,
        post_gen: Optional[PostGenerator] = None,
    ) -> Optional[str]:
        """PostGenerator를 통해 Jekyll 포스트를 생성합니다.

        ``post_gen`` 을 지정하면 해당 인스턴스를 사용합니다 (카테고리가
        다른 포스트를 생성할 때 유용).

        Returns:
            생성된 파일 경로, 또는 스킵 시 ``None``.
        """
        gen = post_gen or self.post_gen
        filepath = gen.create_post(
            title=title,
            content=content,
            date=self.now,
            logical_date=logical_date or self.today,
            tags=tags,
            source=source,
            lang=lang,
            image=image,
            extra_frontmatter=extra_frontmatter,
            slug=slug,
        )
        if filepath:
            self._created_count += 1
        return filepath

    def save_state(self) -> None:
        """중복 방지 상태를 디스크에 저장합니다."""
        self.dedup.save()

    def log_summary(
        self,
        items: List[Dict[str, Any]],
        *,
        extras: Optional[Dict[str, Any]] = None,
    ) -> None:
        """수집 결과 메트릭 로그를 출력합니다."""
        unique_items = len(
            {
                f"{item.get('title', '')}|{item.get('source', '')}|{item.get('link', '')}"
                for item in items
                if item.get("title")
            }
        )
        source_count = len(
            {item.get("source", "") for item in items if item.get("source")}
        )
        log_collection_summary(
            self.logger,
            collector=f"collect_{self.name}",
            source_count=source_count,
            unique_items=unique_items,
            post_created=self._created_count,
            started_at=self._started_at,
            extras=extras,
        )

    def run(self) -> None:
        """메인 실행 파이프라인.

        서브클래스에서 오버라이드하여 다중 포스트 생성 등
        복잡한 파이프라인을 구현할 수 있습니다.
        """
        self.logger.info("=== Starting %s collection ===", self.name)
        self._started_at = time.monotonic()

        items = self.fetch()
        items = self.deduplicate(items)
        items = self.process(items)

        if not items:
            self.logger.info("새 뉴스 없음")
            self.save_state()
            self.log_summary([])
            return

        content = self.build_content(items)
        title = self.build_title(items)

        if not self.is_duplicate_exact(title, "consolidated"):
            filepath = self.create_post(
                title=title,
                content=content,
                tags=self.default_tags(),
                source="consolidated",
            )
            if filepath:
                self.mark_seen(title, "consolidated")
                self.logger.info("Created post: %s", filepath)

        self.save_state()
        self.logger.info(
            "=== %s collection complete: %d posts created ===",
            self.name,
            self._created_count,
        )
        self.log_summary(items)

    def build_title(self, items: List[Dict[str, Any]]) -> str:
        """포스트 제목을 생성합니다.

        서브클래스에서 오버라이드 가능합니다.
        """
        return f"{self.category} 뉴스 브리핑 - {self.today}"

    def default_tags(self) -> List[str]:
        """기본 태그 목록을 반환합니다.

        서브클래스에서 오버라이드 가능합니다.
        """
        return [self.category, "news", "daily-digest"]
