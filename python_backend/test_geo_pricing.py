"""Unit tests for geo pricing Phase 1 (run: python3 -m pytest test_geo_pricing.py -q)"""

import geo_competitor_scan as gcs
from geo_pricing_report import (
    MIN_MARGIN, PSP_FEE_RATE, UNDERCUT, classify_variant, margin_floor_for_rank,
    propose_price, round_psychological,
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
    # AUD market: floor should be in AUD (divisor = 1 - 35% margin - 5% PSP)
    p_usd = propose_price(10.0, 100.0, 1.0, 50.0)
    p_aud = propose_price(10.0, 100.0, 1.52, 50.0)
    assert p_aud["floor"] > p_usd["floor"]
    assert abs(p_aud["floor"] - round(10.0 * 1.52 / 0.60, 2)) < 0.01


def test_undercut_pct():
    assert UNDERCUT == 0.04


def test_margin_tiers_by_rank():
    assert margin_floor_for_rank(1) == 0.35    # traffic driver (user floor 35%)
    assert margin_floor_for_rank(50) == 0.35
    assert margin_floor_for_rank(51) == 0.40   # mid catalog
    assert margin_floor_for_rank(300) == 0.40
    assert margin_floor_for_rank(301) == 0.50  # long tail
    assert margin_floor_for_rank(None) == 0.50  # never sold -> long tail


# ---------- per-variant playbook ----------

def test_playbook_cut_when_winnable():
    # cogs 10 -> floor 16.67; comp 40 -> target 38.4 >= floor; current 45
    r = classify_variant(10.0, 40.0, 1.0, 45.0, min_margin=0.35)
    assert r["case"] == "cut"
    assert r["proposed"] == 37.95


def test_playbook_raise_capped():
    # target 38.4 vs current 20 -> +92%, but that's > SUSPECT_DELTA -> quarantine
    r = classify_variant(10.0, 40.0, 1.0, 20.0, min_margin=0.35)
    assert r["case"] == "quarantine"
    # +30% gap -> raise, capped at +25%
    r2 = classify_variant(10.0, 40.0, 1.0, 29.5, min_margin=0.35)
    assert r2["case"] == "raise"
    assert r2["proposed"] <= round(29.5 * 1.25, 2) + 0.95


def test_playbook_floor_near():
    # cogs 20 -> floor 33.33; comp 31 -> target 29.76 < floor,
    # floor <= comp*1.15 (35.65) -> price at floor
    r = classify_variant(20.0, 31.0, 1.0, 45.0, min_margin=0.35)
    assert r["case"] == "floor-near"
    assert r["proposed"] >= r["floor"] - 0.5


def test_playbook_hold_value_machine():
    # the machine case: cogs 190 -> floor 316.67; comp avg 209 -> target 200.6
    # floor is 51% above market (> comp*1.15) -> hold price, value strategy
    r = classify_variant(190.0, 209.0, 1.0, 543.0, min_margin=0.35,
                         price_usd=543.0)
    assert r["case"] == "hold-value"
    assert r["proposed"] == 543.0  # price untouched
    assert "sourcing" in r["action"]  # high-ticket flag


def test_playbook_floor_near_guarded_against_bad_match():
    # target below floor and floor within 15% of comp, but repricing to floor
    # would move the price >50% -> verify the match first
    # cogs 20 -> floor 33.33; comp 31; current 90 -> floor cut is -63%
    r = classify_variant(20.0, 31.0, 1.0, 90.0, min_margin=0.35)
    assert r["case"] == "quarantine"


def test_playbook_thin_data_quarantine():
    r = classify_variant(10.0, 40.0, 1.0, 41.0, min_margin=0.35, comp_count=2)
    assert r["case"] == "quarantine"


def test_playbook_no_data_keeps():
    r = classify_variant(10.0, 0.0, 1.0, 41.0, min_margin=0.35)
    assert r["case"] == "no-data"
    assert r["proposed"] == 41.0


# ---------- hybrid master/override ----------

def test_master_override_split(tmp_path, monkeypatch):
    import geo_pricing_report as gpr
    monkeypatch.setattr(gpr, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(gpr, "SALES_FILE", tmp_path / "sales.json")
    monkeypatch.setattr(gpr, "FX_CACHE_FILE", tmp_path / "fx.json")
    (tmp_path / "sales.json").write_text(
        '{"built_at": "x", "variants": {'
        '"1": {"variant_id": "1", "product_title": "A", "variant_title": "",'
        ' "sku": "", "units": 5, "revenue": 500.0},'
        '"2": {"variant_id": "2", "product_title": "B", "variant_title": "",'
        ' "sku": "", "units": 5, "revenue": 400.0}}}')

    # AU comp data: variant 1 target ~= US master * fx (master mode);
    # variant 2 target far above (override mode)
    geo_store = {
        "au": {
            "1": {"comp_avg": 31.2, "comp_low": 30, "comp_high": 33,
                  "currency": "AUD", "filtered_count": 8},
            "2": {"comp_avg": 60.0, "comp_low": 55, "comp_high": 66,
                  "currency": "AUD", "filtered_count": 8},
        }
    }
    monkeypatch.setattr(gpr, "get_competitor_stats",
                        lambda geo, vid: geo_store.get(geo, {}).get(str(vid)))

    items = [
        {"variant_id": "1", "item": "A", "cogs": 8.0, "retail_base": 25.0},
        {"variant_id": "2", "item": "B", "cogs": 12.0, "retail_base": 30.0},
    ]
    fx = {"USD": 1.0, "AUD": 1.5}
    # master: US proposed 20.0 for v1 -> AU master price 30.0; AU target
    # 31.2*0.96=29.95 -> within 10% -> master. v2 master 32 -> AU target
    # 57.6 -> override (raise)
    s = gpr.generate_market_report(
        "au", items, fx, master_prices_usd={"1": 20.0, "2": 32.0})
    import csv as _csv
    with open(s["csv"]) as f:
        by_id = {r["variant_id"]: r for r in _csv.DictReader(f)}
    assert by_id["1"]["pricing_mode"] == "master"
    assert by_id["2"]["pricing_mode"] == "override"
    assert s["pricing_modes"] == {"master": 1, "override": 1}


def test_tiered_floor_changes_proposal():
    # long-tail floor (50%) forces a higher price than driver floor (30%)
    driver = propose_price(10.0, 18.0, 1.0, 20.0, min_margin=0.30)
    tail = propose_price(10.0, 18.0, 1.0, 20.0, min_margin=0.50)
    assert tail["floor"] > driver["floor"]
    assert tail["note"] == "floor"


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
