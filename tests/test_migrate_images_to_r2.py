"""tests/test_migrate_images_to_r2.py — migrate_images_to_r2 스크립트 단위 테스트.

boto3/R2 실호출 없이 mock으로만 검증.
테스트 환경 패턴은 tests/test_asset_storage.py 스타일을 따른다.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# scripts/ 경로 삽입 (conftest.py 가 이미 하지만 standalone 실행 대비)
_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import migrate_images_to_r2 as _m  # noqa: E402

from common import asset_storage  # noqa: E402

_R2_ENV = {
    "R2_ACCOUNT_ID": "acct123",
    "R2_ACCESS_KEY_ID": "ak",
    "R2_SECRET_ACCESS_KEY": "sk",
    "R2_BUCKET": "imgbucket",
    "R2_PUBLIC_BASE_URL": "https://img.example.com/",
}

_GENERATED_PNG = "news-briefing-crypto-2026-03-20.png"
_CDN_URL = "https://img.example.com/generated/news-briefing-crypto-2026-03-20.png"
_LOCAL_IMAGE_URL = f"/assets/images/generated/{_GENERATED_PNG}"

_POST_TEMPLATE = """\
---
layout: post
title: "테스트 포스트"
date: 2026-03-20 09:00:00 +0900
categories: crypto-news
description: "테스트 설명"
image: "{image_url}"
permalink: "/crypto-news/2026/03/20/test-post/"
---

본문 내용입니다.
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_r2_cache():
    """각 테스트 전후로 asset_storage lru_cache 초기화."""
    asset_storage.reset_cache()
    yield
    asset_storage.reset_cache()


@pytest.fixture
def disabled_env(monkeypatch):
    for key in _R2_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def enabled_env(monkeypatch):
    for key, val in _R2_ENV.items():
        monkeypatch.setenv(key, val)


def _make_posts_dir(tmp_path: Path, image_url: str = _LOCAL_IMAGE_URL) -> tuple[Path, Path]:
    """tmp_path 아래 posts/ 디렉토리와 샘플 포스트 파일 생성. (posts_dir, post_file) 반환."""
    posts_dir = tmp_path / "_posts"
    posts_dir.mkdir()
    post_file = posts_dir / "2026-03-20-test-post.md"
    post_file.write_text(_POST_TEMPLATE.format(image_url=image_url), encoding="utf-8")
    return posts_dir, post_file


def _make_local_png(tmp_path: Path, filename: str = _GENERATED_PNG) -> Path:
    """tmp_path 아래 assets/images/generated/{filename} 생성."""
    gen_dir = tmp_path / "assets" / "images" / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)
    png = gen_dir / filename
    png.write_bytes(b"fake-png")
    return png


# ---------------------------------------------------------------------------
# collect_candidates
# ---------------------------------------------------------------------------


class TestCollectCandidates:
    def test_로컬_파일_없으면_skip(self, disabled_env, tmp_path):
        """로컬 png가 없으면 후보 목록에 포함되지 않는다."""
        posts_dir, _ = _make_posts_dir(tmp_path)
        # png 파일을 만들지 않음
        result = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path)
        assert result == []

    def test_로컬_파일_있으면_포함(self, disabled_env, tmp_path):
        """로컬 png가 있으면 후보에 포함된다."""
        posts_dir, _ = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)
        result = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path)
        assert len(result) == 1
        assert result[0]["filename"] == _GENERATED_PNG

    def test_generated_prefix_아닌_image는_skip(self, disabled_env, tmp_path):
        """image: 가 /assets/images/generated/ 외 경로면 skip."""
        posts_dir, _ = _make_posts_dir(tmp_path, image_url="/assets/images/other/foo.png")
        # png 파일은 만들지 않아도 됨 — 애초에 regex 매칭 자체가 실패해야 함
        result = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path)
        assert result == []

    def test_limit_적용(self, disabled_env, tmp_path):
        """--limit N 이 정확히 N건만 반환한다."""
        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()
        gen_dir = tmp_path / "assets" / "images" / "generated"
        gen_dir.mkdir(parents=True)
        for i in range(5):
            fname = f"news-briefing-crypto-2026-03-{i + 10:02d}.png"
            (gen_dir / fname).write_bytes(b"x")
            post = posts_dir / f"2026-03-{i + 10:02d}-post.md"
            post.write_text(
                _POST_TEMPLATE.format(image_url=f"/assets/images/generated/{fname}"),
                encoding="utf-8",
            )
        result = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path, limit=3)
        assert len(result) == 3

    def test_days_필터(self, disabled_env, tmp_path):
        """--days N 으로 날짜 범위 밖 포스트는 제외된다."""
        posts_dir, _ = _make_posts_dir(tmp_path)  # date: 2026-03-20
        _make_local_png(tmp_path)
        # days=1 → cutoff = 오늘 - 0일. 2026-03-20은 과거이므로 제외
        result = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path, days=1)
        assert result == []

    def test_cdn_url_포함(self, enabled_env, tmp_path):
        """후보 항목에 cdn_url 이 올바르게 설정된다."""
        posts_dir, _ = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)
        result = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path)
        assert len(result) == 1
        assert result[0]["cdn_url"] == _CDN_URL


# ---------------------------------------------------------------------------
# run_dry_run
# ---------------------------------------------------------------------------


class TestRunDryRun:
    def test_dry_run_파일_수정_없음(self, disabled_env, tmp_path):
        """dry-run은 어떤 파일도 수정하지 않는다."""
        posts_dir, post_file = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)
        original = post_file.read_text(encoding="utf-8")

        candidates = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path)
        _m.run_dry_run(candidates)

        assert post_file.read_text(encoding="utf-8") == original

    def test_dry_run_bak_파일_생성_없음(self, disabled_env, tmp_path):
        """dry-run은 .bak 파일도 생성하지 않는다."""
        posts_dir, post_file = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)

        candidates = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path)
        _m.run_dry_run(candidates)

        bak = post_file.with_suffix(".md.bak")
        assert not bak.exists()


# ---------------------------------------------------------------------------
# run_apply — is_enabled False
# ---------------------------------------------------------------------------


class TestRunApplyDisabled:
    def test_r2_미활성화면_거부_쓰기_없음(self, disabled_env, tmp_path):
        """is_enabled()가 False면 run_apply가 -1을 반환하고 파일을 수정하지 않는다."""
        posts_dir, post_file = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)
        original = post_file.read_text(encoding="utf-8")

        candidates = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path)
        result = _m.run_apply(candidates)

        assert result == -1
        assert post_file.read_text(encoding="utf-8") == original

    def test_r2_미활성화면_bak_없음(self, disabled_env, tmp_path):
        posts_dir, post_file = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)

        candidates = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path)
        _m.run_apply(candidates)

        bak = post_file.with_suffix(".md.bak")
        assert not bak.exists()


# ---------------------------------------------------------------------------
# run_apply — is_enabled True + 업로드 성공
# ---------------------------------------------------------------------------


class TestRunApplyEnabled:
    def test_apply_성공_image_cdn_url로_치환(self, enabled_env, monkeypatch, tmp_path):
        """is_enabled=True + 업로드 성공 시 image: 가 CDN URL로 치환된다."""
        posts_dir, post_file = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)

        monkeypatch.setattr(asset_storage, "_client", lambda: MagicMock())

        candidates = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path)
        result = _m.run_apply(candidates)

        assert result == 1
        new_content = post_file.read_text(encoding="utf-8")
        assert _CDN_URL in new_content
        assert _LOCAL_IMAGE_URL not in new_content

    def test_apply_성공_본문_보존(self, enabled_env, monkeypatch, tmp_path):
        """image: 라인만 바뀌고 나머지 front matter·본문은 그대로다."""
        posts_dir, post_file = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)
        original = post_file.read_text(encoding="utf-8")

        monkeypatch.setattr(asset_storage, "_client", lambda: MagicMock())

        candidates = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path)
        _m.run_apply(candidates)

        new_content = post_file.read_text(encoding="utf-8")
        # 본문 라인이 남아 있어야 함
        assert "본문 내용입니다." in new_content
        # title, description 등 다른 필드 보존
        assert 'title: "테스트 포스트"' in new_content
        assert 'description: "테스트 설명"' in new_content
        # image: 만 바뀐 것 확인
        # 원본 템플릿: image: "/assets/images/generated/foo.png"
        # 치환 결과: image: "https://cdn/generated/foo.png"
        assert original.replace(f'"{_LOCAL_IMAGE_URL}"', f'"{_CDN_URL}"') == new_content

    def test_apply_성공_bak_파일_생성(self, enabled_env, monkeypatch, tmp_path):
        """apply 성공 시 .bak 백업 파일이 생성된다."""
        posts_dir, post_file = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)
        original = post_file.read_text(encoding="utf-8")

        monkeypatch.setattr(asset_storage, "_client", lambda: MagicMock())

        candidates = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path)
        _m.run_apply(candidates)

        bak = post_file.with_suffix(".md.bak")
        assert bak.exists()
        assert bak.read_text(encoding="utf-8") == original

    def test_upload_실패_시_skip_파일_수정_없음(self, enabled_env, monkeypatch, tmp_path):
        """업로드 실패 시 해당 포스트를 skip하고 파일을 수정하지 않는다."""
        posts_dir, post_file = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)
        original = post_file.read_text(encoding="utf-8")

        client = MagicMock()
        client.put_object.side_effect = RuntimeError("네트워크 오류")
        monkeypatch.setattr(asset_storage, "_client", lambda: client)

        candidates = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path)
        result = _m.run_apply(candidates)

        assert result == 0
        assert post_file.read_text(encoding="utf-8") == original

    def test_여러_포스트_부분_성공(self, enabled_env, monkeypatch, tmp_path):
        """업로드 성공/실패가 섞인 경우 성공한 것만 치환한다."""
        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()
        gen_dir = tmp_path / "assets" / "images" / "generated"
        gen_dir.mkdir(parents=True)

        fnames = ["news-briefing-crypto-2026-03-20.png", "news-briefing-crypto-2026-03-21.png"]
        post_files = []
        for i, fname in enumerate(fnames):
            (gen_dir / fname).write_bytes(b"x")
            pf = posts_dir / f"2026-03-{20 + i}-post.md"
            pf.write_text(
                _POST_TEMPLATE.format(image_url=f"/assets/images/generated/{fname}"),
                encoding="utf-8",
            )
            post_files.append(pf)

        call_count = 0

        def _selective_put(**kwargs):
            nonlocal call_count
            call_count += 1
            if "2026-03-20" in kwargs.get("Key", ""):
                raise RuntimeError("의도적 실패")

        client = MagicMock()
        client.put_object.side_effect = _selective_put
        monkeypatch.setattr(asset_storage, "_client", lambda: client)

        candidates = _m.collect_candidates(posts_dir=posts_dir, repo_root=tmp_path)
        result = _m.run_apply(candidates)

        assert result == 1
        # 첫 번째 포스트: 업로드 실패 → 원본 유지
        assert _LOCAL_IMAGE_URL in post_files[0].read_text(encoding="utf-8")
        # 두 번째 포스트: 성공 → CDN URL
        cdn2 = "https://img.example.com/generated/news-briefing-crypto-2026-03-21.png"
        assert cdn2 in post_files[1].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# _replace_image_url 단위 테스트
# ---------------------------------------------------------------------------


class TestReplaceImageUrl:
    def test_따옴표_있는_image_치환(self):
        content = _POST_TEMPLATE.format(image_url=_LOCAL_IMAGE_URL)
        result = _m._replace_image_url(content, _CDN_URL)
        assert f'image: "{_CDN_URL}"' in result
        assert _LOCAL_IMAGE_URL not in result

    def test_따옴표_없는_image_치환(self):
        content = "image: /assets/images/generated/foo-2026-03-20.png\n"
        result = _m._replace_image_url(content, "https://cdn.example.com/generated/foo-2026-03-20.png")
        assert 'image: "https://cdn.example.com/generated/foo-2026-03-20.png"' in result

    def test_본문에_image_키워드_있어도_front_matter만_치환(self):
        content = '---\nimage: "/assets/images/generated/foo-2026-03-20.png"\n---\n본문에서 image: 언급\n'
        result = _m._replace_image_url(content, "https://cdn.example.com/generated/foo.png")
        # 본문의 image: 는 건드리지 않음
        assert "본문에서 image: 언급" in result


# ---------------------------------------------------------------------------
# main() CLI — dry-run 은 쓰기 없음
# ---------------------------------------------------------------------------


class TestMainCli:
    def test_main_dry_run_기본_쓰기_없음(self, disabled_env, tmp_path):
        """인자 없이 실행(dry-run 기본)하면 파일 수정 없이 0을 반환한다."""
        posts_dir, post_file = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)
        original = post_file.read_text(encoding="utf-8")

        with patch("sys.argv", ["migrate_images_to_r2.py", f"--posts-dir={posts_dir}", f"--repo-root={tmp_path}"]):
            exit_code = _m.main()

        assert exit_code == 0
        assert post_file.read_text(encoding="utf-8") == original

    def test_main_apply_r2_미활성화면_exit1(self, disabled_env, tmp_path):
        """--apply 인데 R2 미활성 → exit code 1, 파일 수정 없음."""
        posts_dir, post_file = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)
        original = post_file.read_text(encoding="utf-8")

        with patch(
            "sys.argv",
            ["migrate_images_to_r2.py", "--apply", f"--posts-dir={posts_dir}", f"--repo-root={tmp_path}"],
        ):
            exit_code = _m.main()

        assert exit_code == 1
        assert post_file.read_text(encoding="utf-8") == original

    def test_main_apply_r2_활성화_치환(self, enabled_env, monkeypatch, tmp_path):
        """--apply + R2 활성화 + 업로드 성공 → image: CDN URL로 치환, exit 0."""
        posts_dir, post_file = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)

        monkeypatch.setattr(asset_storage, "_client", lambda: MagicMock())

        with patch(
            "sys.argv",
            ["migrate_images_to_r2.py", "--apply", f"--posts-dir={posts_dir}", f"--repo-root={tmp_path}"],
        ):
            exit_code = _m.main()

        assert exit_code == 0
        assert _CDN_URL in post_file.read_text(encoding="utf-8")

    def test_main_apply_전체_업로드_실패면_exit1(self, enabled_env, monkeypatch, tmp_path):
        """--apply + R2 활성화인데 모든 업로드가 실패 → 0건 성공이므로 exit 1, 파일 수정 없음."""
        posts_dir, post_file = _make_posts_dir(tmp_path)
        _make_local_png(tmp_path)
        original = post_file.read_text(encoding="utf-8")

        client = MagicMock()
        client.put_object.side_effect = RuntimeError("네트워크 오류")
        monkeypatch.setattr(asset_storage, "_client", lambda: client)

        with patch(
            "sys.argv",
            ["migrate_images_to_r2.py", "--apply", f"--posts-dir={posts_dir}", f"--repo-root={tmp_path}"],
        ):
            exit_code = _m.main()

        assert exit_code == 1
        assert post_file.read_text(encoding="utf-8") == original
