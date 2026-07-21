# Geo Pricing — Phase 1 (Research & Dry-Run) Design

Date: 2026-07-21
Status: Approved by Kapi (brainstorm session). Phase 1 = build + analyze only.

## Strategy context

Mirai Skin is shifting from ads-led ("price chases Google CPC economics") to
SEO/organic-led pricing:

- **Product price** becomes competitive per country: undercut Google Shopping
  competitor average, with a hard margin floor. The old `$15 ad-CPA` term and
  the shipping-cost term are removed from the price target.
- **Delivery fee** (Phase 2, NOT in scope now): flat per-country fee at actual
  matrix cost + buffer; free-delivery threshold ~30% above median basket.
  Per user decision 2026-07-21: **delivery/shipping settings are not touched at all
  in Phase 1.**
- **Free-delivery weight cap** (user-raised risk, 2026-07-21): a price-only
  threshold lets heavy low-margin baskets ship free at a loss (real 2026 worst
  case: $63 order, 2.8 kg, $38 ship). Data: 5% of US orders in the $49-80 band
  are >1 kg; 1% lose money at blended margin, 5% at the 30% floor margin.
  Phase 2 rule: free delivery requires subtotal >= threshold AND order weight
  <= 1 kg; heavier orders pay a weight-based rate. With the cap, a $59
  threshold is safe even at pure floor margin (0.30 x 59 = $17.70 covers any
  <=1 kg cost). Implementation: stack TOTAL_PRICE + TOTAL_WEIGHT method
  conditions via the delivery-profile API (verify - the admin UI doesn't allow
  mixing, but the store's Selfnamed profile already stacks two weight
  conditions on one rate); fallback: move heavy SKUs to a separate "Heavy
  items" delivery profile with no free rate.

2026 YTD facts the design rests on (3,188 orders): revenue concentrated in
US ($142k), AU ($33k), UK ($12k), CA ($10k); blended gross margin 49–54%;
median basket ~$37–48; weight ≈ 0.8 kg per $100 of basket.

## Phase 1 scope

Build the research + analysis system. **Zero writes to Shopify.** Outputs are
dry-run reports for human review.

1. **Per-country competitor research** (the critical unlock):
   - Existing scanner (`pricing_execution.check_competitor_prices`) uses
     SerpAPI Google Shopping with hardcoded `gl: "us"`.
   - New module parameterizes geo: `us`, `au`, `gb`, `ca` (SerpAPI `gl` +
     matching `google_domain`); results come back in local currency
     (USD/AUD/GBP/CAD).
   - Per-geo persistence: `competitor_data_geo.json` keyed
     `geo -> variant_id -> {comp_low, comp_avg, comp_high, currency, counts,
     top_sellers, scanned_at}`. The legacy US file `competitor_data.json` is
     left intact and readable as a fallback US source.
   - Reuses `smart_pricing.is_trusted_seller` + `filter_outlier_prices`.
   - Cost control: scan `--top N` variants ranked by 2026 revenue (default 50),
     `--geos` selectable. Sales ranking cached to
     `outputs/variant_sales_2026.json` (refreshable via `--refresh-sales`).
   - `--mock` mode (canned SerpAPI fixtures) so the pipeline is testable
     without the key. SERPAPI_KEY currently exists only in Render env — to run
     real scans locally the key must be added to `.env`.

2. **Per-market pricing engine** (`geo_pricing_report.py`):
   - Markets = Shopify Markets that exist in the store: US (base/USD),
     AU (AUD price list), UK (GBP), CA (CAD). Store already has price lists at
     0% adjustment, so current local price = base USD price x FX.
   - Proposed price per variant per market:
     - `target = comp_avg_local * (1 - UNDERCUT)` with `UNDERCUT = 0.04`
     - `floor = COGS_usd * FX / (1 - MIN_MARGIN - PSP_FEE)` with
       `MIN_MARGIN = 0.30` (of price), `PSP_FEE = 0.05`
     - `proposed = max(target, floor)`; note says which bound won.
     - No comp data for that geo -> fall back to US comp data x FX
       (marked `proxy`), else `no-data` (keep current).
     - Psychological rounding to `.95` (never rounds below floor).
   - FX: live from open.er-api.com (free, no key) cached to
     `outputs/fx_rates.json`; static fallback constants if offline.
   - Output per market: `outputs/geo_pricing_proposal_{geo}_{date}.csv` (+ a
     combined JSON) with: variant, item, 2026 units/revenue, COGS, current
     local price, comp low/avg/high, proposed, delta %, margin % at proposed,
     note. Sorted by 2026 revenue desc. Console summary: counts, revenue-
     weighted avg delta, # at floor, # proxy, # no-data.

3. **CLI orchestrator** (`run_geo_pricing.py`):
   `python3 run_geo_pricing.py scan --geos au,gb --top 50` and
   `python3 run_geo_pricing.py report --geos us,au,gb,ca`.
   Explicitly no `apply`/write subcommand in Phase 1.

## Non-goals (Phase 2+)

- Writing prices to Shopify price lists (`priceListFixedPricesAdd`).
- Any change to delivery profiles/zones/fees/thresholds (incl. the discovered
  Asia "free over 80 kg" misconfiguration — flagged to user, fix separately).
- Dashboard UI wiring.
- Splitting the Europe market for per-country EU pricing.

## Testing

`test_geo_pricing.py`: unit tests for price math (undercut, floor, rounding,
proxy fallback), SerpAPI response parsing with fixtures, FX fallback path.
Real-data smoke: generate the US report from the existing
`competitor_data.json` scan data.

## Risks / open items

- SerpAPI quota: 4 geos x top-50 = 200 searches per full refresh. Fine on paid
  plan; `--top` guards runaway cost.
- AU/UK/CA Google Shopping coverage for K-beauty items may be thinner than US;
  the proxy fallback covers gaps but real local scans are preferred.
- Trusted-seller list is US-centric; geo-specific untrusted marketplaces can be
  added to `UNTRUSTED_SELLERS` as scans reveal them.
