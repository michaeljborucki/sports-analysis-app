from unittest.mock import patch, MagicMock
from scrapers.meta import fetch_patch_context, _patch_cache

def test_fetch_returns_required_keys():
    _patch_cache.clear()
    with patch("scrapers.meta.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            text="<html>Patch 14.5 notes here</html>",
        )
        mock_get.return_value.raise_for_status = MagicMock()
        result = fetch_patch_context("lol")

    assert "patch_version" in result
    assert "days_since_patch" in result
    assert "key_changes" in result
    assert "impact_rating" in result
    assert "raw_url" in result

def test_fetch_unknown_game():
    _patch_cache.clear()
    result = fetch_patch_context("unknown_game")
    assert result["patch_version"] == "unknown"
    assert result["raw_url"] == ""

def test_caching():
    _patch_cache.clear()
    _patch_cache["cs2"] = {
        "patch_version": "1.39",
        "days_since_patch": 3,
        "key_changes": ["test"],
        "impact_rating": "minor",
        "raw_url": "https://...",
    }
    result = fetch_patch_context("cs2")
    assert result["patch_version"] == "1.39"

def test_lol_version_extraction():
    from scrapers.meta import _extract_patch_version
    html = '<h2>Patch 14.5 Notes</h2>'
    assert _extract_patch_version(html, "lol") == "14.5"
