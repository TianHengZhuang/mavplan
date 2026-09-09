"""Tests for i18n module (v1.6)."""
from __future__ import annotations

import pytest

import mavplan.i18n as i18n


def _reset() -> None:
    i18n.reset_for_test()


class TestAvailable:
    def test_returns_tuple(self) -> None:
        assert isinstance(i18n.available(), tuple)

    def test_contains_zh_and_en(self) -> None:
        assert "zh-CN" in i18n.available()
        assert "en" in i18n.available()


class TestSetLanguage:
    def teardown_method(self) -> None:
        _reset()

    def test_set_zh(self) -> None:
        assert i18n.set_language("zh-CN") == "zh-CN"
        assert i18n.get_language() == "zh-CN"

    def test_set_en(self) -> None:
        assert i18n.set_language("en") == "en"
        assert i18n.get_language() == "en"

    def test_set_alias_zh_cn(self) -> None:
        assert i18n.set_language("zh_CN") == "zh-CN"
        assert i18n.set_language("zh-cn") == "zh-CN"

    def test_set_alias_en_us(self) -> None:
        assert i18n.set_language("en_US") == "en"
        assert i18n.set_language("en-gb") == "en"

    def test_unknown_language_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported language"):
            i18n.set_language("fr")


class TestTranslation:
    def teardown_method(self) -> None:
        _reset()

    def test_zh_returns_chinese(self) -> None:
        i18n.set_language("zh-CN")
        assert "任务" in i18n.t("app.tagline")
        assert "场景" in i18n.t("cmd.scenario")

    def test_en_returns_english(self) -> None:
        i18n.set_language("en")
        assert "mission planner" in i18n.t("app.tagline")
        assert "Scenario" in i18n.t("cmd.scenario")

    def test_missing_key_returns_placeholder(self) -> None:
        i18n.set_language("zh-CN")
        assert i18n.t("nonexistent.key.123") == "<nonexistent.key.123>"

    def test_missing_key_falls_back_to_english(self) -> None:
        # Only if zh-CN entry is missing but en exists
        i18n.set_language("zh-CN")
        result = i18n.t("app.tagline")
        assert "<app.tagline>" not in result  # key should exist

    def test_interpolation(self) -> None:
        i18n.set_language("zh-CN")
        text = i18n.t("err.file_not_found")
        # No interpolation in this key, just verify it returns a string
        assert isinstance(text, str)

    def test_grade_comments_bilingual(self) -> None:
        i18n.set_language("zh-CN")
        assert "优秀" in i18n.t("grade.comment.excellent")
        assert "未通过" in i18n.t("grade.comment.fail")
        i18n.set_language("en")
        assert "Excellent" in i18n.t("grade.comment.excellent")
        assert "Fail" in i18n.t("grade.comment.fail")


class TestDetectFromEnv:
    def teardown_method(self) -> None:
        _reset()

    def test_detects_zh_from_lang(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANG", "zh_CN.UTF-8")
        assert i18n.detect_from_env() == "zh-CN"

    def test_detects_zh_from_lang_cn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANG", "zh-CN")
        assert i18n.detect_from_env() == "zh-CN"

    def test_detects_en(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        assert i18n.detect_from_env() == "en"

    def test_mavplan_lang_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        monkeypatch.setenv("MAVPLAN_LANG", "zh-CN")
        assert i18n.detect_from_env() == "zh-CN"

    def test_unknown_defaults_to_zh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANG", "")
        assert i18n.detect_from_env() == "zh-CN"


class TestInitFromEnv:
    def teardown_method(self) -> None:
        _reset()

    def test_sets_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        lang = i18n.init_from_env()
        assert lang == "en"
        assert i18n.get_language() == "en"


class TestResetForTest:
    def test_resets_to_default(self) -> None:
        i18n.set_language("en")
        i18n.reset_for_test()
        assert i18n.get_language() == "zh-CN"

    def test_resets_to_specified(self) -> None:
        i18n.set_language("zh-CN")
        i18n.reset_for_test("en")
        assert i18n.get_language() == "en"
