"""Unit tests for scripts/common/asset_storage.py (R2 image mirroring).

The real R2 upload path cannot be exercised without live credentials/bucket, so
boto3 is mocked. These tests pin the contract that matters: graceful degradation
(no-op when disabled) and correct upload parameters when enabled.
"""

from unittest.mock import MagicMock

import pytest

from common import asset_storage

_R2_ENV = {
    "R2_ACCOUNT_ID": "acct123",
    "R2_ACCESS_KEY_ID": "ak",
    "R2_SECRET_ACCESS_KEY": "sk",
    "R2_BUCKET": "imgbucket",
    "R2_PUBLIC_BASE_URL": "https://img.example.com/",
}


@pytest.fixture(autouse=True)
def _clear_client_cache():
    """Reset the memoized client around every test."""
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


def _make_variants(tmp_path, stem="news-briefing-crypto-2026-03-20"):
    """Create png/webp/avif under a generated/ dir; return the png path."""
    gen_dir = tmp_path / "assets" / "images" / "generated"
    gen_dir.mkdir(parents=True)
    png = gen_dir / f"{stem}.png"
    for ext in (".png", ".webp", ".avif"):
        (gen_dir / f"{stem}{ext}").write_bytes(b"fake-image-bytes")
    return str(png)


# --------------------------------------------------------------------------- #
# is_enabled
# --------------------------------------------------------------------------- #
def test_disabled_when_no_env(disabled_env):
    assert asset_storage.is_enabled() is False


def test_disabled_when_partial_env(monkeypatch, disabled_env):
    # Only some of the required vars set → still disabled
    monkeypatch.setenv("R2_BUCKET", "imgbucket")
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct")
    assert asset_storage.is_enabled() is False


def test_enabled_when_all_env(enabled_env):
    assert asset_storage.is_enabled() is True


# --------------------------------------------------------------------------- #
# public_url
# --------------------------------------------------------------------------- #
def test_public_url_local_when_disabled(disabled_env):
    assert (
        asset_storage.public_url("news-briefing-crypto-2026-03-20.png")
        == "/assets/images/generated/news-briefing-crypto-2026-03-20.png"
    )


def test_public_url_cdn_when_enabled(enabled_env):
    # trailing slash on base URL must be normalized
    assert asset_storage.public_url("foo-2026-03-20.png") == "https://img.example.com/generated/foo-2026-03-20.png"


def test_public_url_uses_basename_only(enabled_env):
    assert (
        asset_storage.public_url("/assets/images/generated/foo-2026-03-20.png")
        == "https://img.example.com/generated/foo-2026-03-20.png"
    )


# --------------------------------------------------------------------------- #
# upload_file
# --------------------------------------------------------------------------- #
def test_upload_noop_when_disabled(disabled_env, tmp_path):
    png = _make_variants(tmp_path)
    assert asset_storage.upload_file(png) is False


def test_upload_false_for_missing_file(enabled_env, tmp_path):
    missing = str(tmp_path / "assets" / "images" / "generated" / "nope-2026-03-20.png")
    assert asset_storage.upload_file(missing) is False


def test_upload_false_for_non_generated_path(enabled_env, monkeypatch, tmp_path):
    other = tmp_path / "elsewhere.png"
    other.write_bytes(b"x")
    monkeypatch.setattr(asset_storage, "_client", lambda: MagicMock())
    assert asset_storage.upload_file(str(other)) is False


def test_upload_calls_put_object_with_correct_params(enabled_env, monkeypatch, tmp_path):
    png = _make_variants(tmp_path)
    client = MagicMock()
    monkeypatch.setattr(asset_storage, "_client", lambda: client)

    assert asset_storage.upload_file(png) is True

    client.put_object.assert_called_once()
    kwargs = client.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "imgbucket"
    assert kwargs["Key"] == "generated/news-briefing-crypto-2026-03-20.png"
    assert kwargs["ContentType"] == "image/png"
    assert "immutable" in kwargs["CacheControl"]


def test_upload_content_type_for_avif(enabled_env, monkeypatch, tmp_path):
    png = _make_variants(tmp_path)
    avif = png[:-4] + ".avif"
    client = MagicMock()
    monkeypatch.setattr(asset_storage, "_client", lambda: client)

    assert asset_storage.upload_file(avif) is True
    assert client.put_object.call_args.kwargs["ContentType"] == "image/avif"


def test_upload_graceful_when_put_object_raises(enabled_env, monkeypatch, tmp_path):
    png = _make_variants(tmp_path)
    client = MagicMock()
    client.put_object.side_effect = RuntimeError("network down")
    monkeypatch.setattr(asset_storage, "_client", lambda: client)

    # Must swallow the error and report failure, never raise
    assert asset_storage.upload_file(png) is False


def test_upload_false_when_client_none(enabled_env, monkeypatch, tmp_path):
    png = _make_variants(tmp_path)
    monkeypatch.setattr(asset_storage, "_client", lambda: None)
    assert asset_storage.upload_file(png) is False


# --------------------------------------------------------------------------- #
# mirror_generated_variants
# --------------------------------------------------------------------------- #
def test_mirror_zero_when_disabled(disabled_env, tmp_path):
    png = _make_variants(tmp_path)
    assert asset_storage.mirror_generated_variants(png) == 0


def test_mirror_uploads_all_three_variants(enabled_env, monkeypatch, tmp_path):
    png = _make_variants(tmp_path)
    client = MagicMock()
    monkeypatch.setattr(asset_storage, "_client", lambda: client)

    assert asset_storage.mirror_generated_variants(png) == 3
    assert client.put_object.call_count == 3
    keys = {c.kwargs["Key"] for c in client.put_object.call_args_list}
    stem = "generated/news-briefing-crypto-2026-03-20"
    assert keys == {f"{stem}.png", f"{stem}.webp", f"{stem}.avif"}


def test_mirror_skips_missing_variants(enabled_env, monkeypatch, tmp_path):
    png = _make_variants(tmp_path)
    # remove the avif sibling
    import os

    os.remove(png[:-4] + ".avif")
    client = MagicMock()
    monkeypatch.setattr(asset_storage, "_client", lambda: client)

    assert asset_storage.mirror_generated_variants(png) == 2


def test_mirror_zero_for_empty_path(enabled_env):
    assert asset_storage.mirror_generated_variants("") == 0


# --------------------------------------------------------------------------- #
# base.py integration hook wiring
# --------------------------------------------------------------------------- #
def test_base_hook_forwards_to_mirror(monkeypatch):
    from common.image_generator import base

    calls = []
    monkeypatch.setattr(asset_storage, "mirror_generated_variants", calls.append)
    base._mirror_to_remote("out/foo-2026-03-20.png")
    assert calls == ["out/foo-2026-03-20.png"]


def test_base_hook_never_raises(monkeypatch):
    from common.image_generator import base

    def boom(_):
        raise RuntimeError("R2 exploded")

    monkeypatch.setattr(asset_storage, "mirror_generated_variants", boom)
    # Must swallow — image generation must never fail because of mirroring
    base._mirror_to_remote("out/foo-2026-03-20.png")
