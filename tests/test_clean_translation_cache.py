import json
from pathlib import Path

import clean_translation_cache as ctc


def _write_cache(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_main_reports_missing_cache(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ctc, "_CACHE_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(ctc.sys, "argv", ["clean_translation_cache.py"])

    ctc.main()

    assert "Translation cache not found, nothing to clean." in capsys.readouterr().out


def test_main_reports_zero_fixes_when_cache_is_clean(tmp_path, monkeypatch, capsys):
    cache_path = tmp_path / "cache.json"
    _write_cache(cache_path, {"abc": "clean text"})

    monkeypatch.setattr(ctc, "_CACHE_PATH", cache_path)
    monkeypatch.setattr(ctc, "_postprocess_translation", lambda value: value)
    monkeypatch.setattr(ctc.sys, "argv", ["clean_translation_cache.py"])

    ctc.main()

    assert "Cache clean: 1 entries, 0 fixes needed." in capsys.readouterr().out


def test_main_dry_run_previews_changes_without_writing(tmp_path, monkeypatch, capsys):
    cache_path = tmp_path / "cache.json"
    _write_cache(cache_path, {"abc12345": "bad artifact", "def67890": "already clean"})

    monkeypatch.setattr(ctc, "_CACHE_PATH", cache_path)
    monkeypatch.setattr(ctc, "_postprocess_translation", lambda value: value.replace("artifact", "output"))
    monkeypatch.setattr(ctc.sys, "argv", ["clean_translation_cache.py", "--dry-run"])

    before = cache_path.read_text(encoding="utf-8")
    ctc.main()
    after = cache_path.read_text(encoding="utf-8")

    assert before == after
    output = capsys.readouterr().out
    assert "[abc12345] bad artifact" in output
    assert "[DRY RUN] Would fix 1 and remove 0 of 2 entries." in output


def test_main_writes_cleaned_cache(tmp_path, monkeypatch, capsys):
    cache_path = tmp_path / "cache.json"
    _write_cache(cache_path, {"abc": "bad artifact"})

    monkeypatch.setattr(ctc, "_CACHE_PATH", cache_path)
    monkeypatch.setattr(ctc, "_postprocess_translation", lambda value: value.replace("artifact", "output"))
    monkeypatch.setattr(ctc.sys, "argv", ["clean_translation_cache.py"])

    ctc.main()

    assert json.loads(cache_path.read_text(encoding="utf-8")) == {"abc": "bad output"}
    assert "Fixed 1, removed 0 of 1 cached translations." in capsys.readouterr().out


def test_main_removes_suffix_mutation_artifacts(tmp_path, monkeypatch, capsys):
    cache_path = tmp_path / "cache.json"
    _write_cache(
        cache_path,
        {
            "k1": "미국 재무부는 트럼프 계정 앱을 출시합니다. 해당 관련 통보.",
            "k2": "1,600% 상승하기 전에 구매해야 할 상위 암호화폐입니다. (1,600% 개정) 광고 관련 알림.",
            "k3": "비트코인이 사상 최고가를 경신했습니다.",  # clean — kept
            "k4": "지정학적 리스크가 커지고 있습니다. 급락 관련 보도.",  # legit 보도 suffix — kept
        },
    )
    monkeypatch.setattr(ctc, "_CACHE_PATH", cache_path)
    monkeypatch.setattr(ctc, "_postprocess_translation", lambda value: value)
    monkeypatch.setattr(ctc.sys, "argv", ["clean_translation_cache.py"])

    ctc.main()

    remaining = json.loads(cache_path.read_text(encoding="utf-8"))
    assert set(remaining) == {"k3", "k4"}  # mutated entries removed, clean + legit kept
    assert "removed 2" in capsys.readouterr().out
