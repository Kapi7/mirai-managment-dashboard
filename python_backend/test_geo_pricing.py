"""Unit tests for geo pricing Phase 1 (run: python3 -m pytest test_geo_pricing.py -q)"""

import geo_competitor_scan as gcs
from geo_pricing_report import (
    MIN_MARGIN, PSP_FEE_RATE, UNDERCUT, propose_price, round_psychological,
)


# ---------- scan parsing ----------

def test_parse_filters_untrusted_and_outliers():
    results = gcs._mock_shopping_results("Some Serum 50ml", "us")
    stats = gcs.parse_shopping_results(results)
    # temu (untrusted) and the 9x outlier must be excluded
    assert stats["filtered_count"] == 5
    assert stats["trusted_count"] == 6  # outlier is trusted but filtered later
    assert 0 < stats["comp_low"] <= stats["comp_avg"] <= stats["comp_high"]
    assert stats["comp_high"] < 2 * stats["comp_avg"]  # outlier really gone


def test_parse_empty():
    stats = gcs.parse_shopping_results([])
    assert stats["comp_avg"] == 0.0
    assert stats["filtered_count"] == 0


def test_build_search_query_skips_default_title():
    q = gcs.build_search_query("COSRX Snail Mucin", "Default Title", "")
    assert q == "COSRX Snail Mucin"
    q2 = gcs.build_search_query("Serum", "50ml", "SKU1")
    assert q2 == "Serum 50ml SKU1"


def test_geo_config_currencies():
    assert gcs.GEO_CONFIG["au"]["currency"] == "AUD"
    assert gcs.GEO_CONFIG["gb"]["currency"] == "GBP"
    assert gcs.GEO_CONFIG["gb"]["gl"] == "uk"  # SerpAPI uses 'uk' for Britain


# ---------- price math ----------

def test_undercut_wins_when_above_floor():
    # cogs 10 USD, comp avg 40 local, fx 1.0 -> target 38.4, floor 15.38
    p = propose_price(10.0, 40.0, 1.0, 30.0)
    assert p["note"] == "undercut"
    assert p["proposed"] == 37.95  # 38.4 -> .95 rounding
    assert p["floor"] == round(10.0 / (1 - MIN_MARGIN - PSP_FEE_RATE), 2)


def test_floor_wins_when_competitors_too_cheap():
    # cogs 20, floor = 20/0.65 = 30.77; comp avg 25 -> target 24 < floor
    p = propose_price(20.0, 25.0, 1.0, 35.0)
    assert p["note"] == "floor"
    assert p["proposed"] >= p["floor"]


def test_no_data_keeps_current():
    p = propose_price(10.0, 0.0, 1.0, 27.5)
    assert p["note"] == "no-data"
    assert p["proposed"] == 27.5


def test_fx_applied_to_floor():
    # AUD market: floor should be in AUD
    p_usd = propose_price(10.0, 100.0, 1.0, 50.0)
    p_aud = propose_price(10.0, 100.0, 1.52, 50.0)
    assert p_aud["floor"] > p_usd["floor"]
    assert abs(p_aud["floor"] - round(10.0 * 1.52 / 0.65, 2)) < 0.01


def test_undercut_pct():
    assert UNDERCUT == 0.04


def test_rounding_never_below_floor():
    assert round_psychological(23.40, 0.0) == 22.95
    assert round_psychological(23.40, 23.0) == 23.95  # 22.95 < floor -> up
    assert round_psychological(0.0, 0.0) == 0.0


# ---------- geo store fallback ----------

def test_us_legacy_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(gcs, "GEO_DATA_FILE", tmp_path / "geo.json")
    legacy = tmp_path / "legacy.json"
    legacy.write_text('{"123": {"comp_low": 9.0, "comp_avg": 20.0, "comp_high": 30.0}}')
    monkeypatch.setattr(gcs, "LEGACY_US_FILE", legacy)
    stats = gcs.get_competitor_stats("us", "123")
    assert stats["comp_avg"] == 20.0
    assert stats["source"] == "legacy_us_file"
    assert gcs.get_competitor_stats("au", "123") is None


def test_scan_variants_mock_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(gcs, "GEO_DATA_FILE", tmp_path / "geo.json")
    variants = [{"variant_id": "111", "product_title": "Test Cream",
                 "variant_title": "50ml", "sku": ""}]
    data = gcs.scan_variants(variants, ["au"], mock=True, progress=False)
    assert data["au"]["111"]["currency"] == "AUD"
    assert data["au"]["111"]["comp_avg"] > 0
    # persisted
    assert gcs.load_geo_data()["au"]["111"]["comp_avg"] == data["au"]["111"]["comp_avg"]
