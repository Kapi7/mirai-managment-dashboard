# Mirai attribution report

`/Attribution` is available from Analytics and the Business Reports navigation.
It uses Mirai's existing dark report components, auth session and Shopify store.

The report provides period, comparison, channel, country and hierarchy dropdowns;
country flags; channel → country → day or country → channel → day expansion;
sortable metrics; pagination; five selectable KPI charts; and a filtered CSV.
Phone cards have visible Sort by / Sort order menus for all five metrics, in
either direction. The selected sort metric is prominent on every card. Sorting
applies before pagination and to country/channel drilldowns; daily rows stay in
date order. Missing conversion values and order-only sessions sort last.
The President-style date slicer offers Today, Yesterday and Last 3 days
(three calendar days including today), plus 7/28 complete days. Its calendar
popover also offers monthly presets and a custom range with Apply/Cancel.
Today is calculated in Mirai's `Asia/Jerusalem` reporting time zone on both
client and server, including around UTC midnight and daylight-saving changes.
Channel, country, comparison and hierarchy menus use the same dark styling.
Changes use arrows and color, with percentage points for conversion, `New` for
a zero previous baseline, and a dash when no session denominator exists.

## Metrics and source boundaries

- Sessions and converted sessions are from ShopifyQL `sessions`.
- Conversion is completed-checkout sessions divided by sessions, including at
  group and total levels. It is never an average of child conversion rates.
- Orders and net sales are from ShopifyQL `sales`. Net sales excludes shipping
  and tax; Shopify sales reversals follow the date they are posted.
- Returning orders use Shopify's historical `new_or_returning_customer` value.
  They are repeat purchases, not product returns/refunds.
- Traffic geography is visitor country; sales geography is shipping country.
  These dimensions are displayed together but never used to calculate a mixed
  orders/sessions conversion rate.
- The channel is Shopify's recorded referring channel plus paid/organic traffic
  type. Non-online-store sales channels (including Shop and subscriptions) stay
  distinct. No referrer is inferred from missing data. This is not a configurable
  first-click, linear or last-non-direct campaign attribution model.
- Exact source aliases (including names, known domains, URL forms and `www`)
  normalize before aggregation, filtering, comparison and export. ChatGPT,
  chat gpt, chatgpt.com and chat.openai.com are one ChatGPT group. Other known AI
  providers follow the same rule. Their organic/unknown referrals combine under
  the provider name without relabeling unknown traffic as organic. Explicit paid
  traffic remains separate. Other providers retain paid/organic distinctions;
  Shop sales channels and shop_app/shop_campaigns remain distinct.
- Direct is not redistributed. Missing UTM sources and internal self-referrers
  are not evidence of an external acquisition source. The current report does
  not carry session-level journeys to infer a prior
  channel. A separate Clicks KPI is omitted because the available ad, search
  and outbound-click counts have different scopes and are not a consistent
  source/country measure for this Shopify report.
- Shop (Shop app / Shop Cash) and other non–Online Store sales channels are
  labeled from `sales_channel` and flagged `orderOnly`. They can have real
  orders and net sales with zero Online Store sessions. The table and phone
  cards show sessions as `n/a`, an Order-only badge, and a footnote. Conversion
  stays `—` because there is no session denominator. Referring channels
  `shop_app` and `shop_campaigns` stay on their own rows and are never added
  to Shop. CSV export keeps the measured session count, including 0, so the
  file still reconciles.
- Independently fetched daily source totals reconcile the detailed rows.
  Shopify can omit visits when grouping by related source/country dimensions;
  the measured residual is displayed as `Unallocated detail` / unknown country.
  It is not spread across known channels. Inconsistent negative count residuals
  fail the request and ask for a reload rather than publishing contradictory data.
- All session traffic is included. The default period ends yesterday. Dates use
  Shopify's reporting time zone, and currency/time zone come from shop metadata.

The previous comparison contains the same number of days immediately before
the selected range. Previous-only groups remain visible as declines. Source
errors, missing columns and the 100,000-row cap fail closed rather than becoming
zero. A successful empty result is shown as no activity.

Schema references: [sessions](https://shopify.dev/docs/api/shopifyql/2026-07/schemas/sessions_and_behavior/sessions),
[sales](https://shopify.dev/docs/api/shopifyql/2026-07/schemas/sales_revenue/sales),
[ShopifyQL Admin API](https://shopify.dev/docs/api/admin-graphql/unstable/queries/shopifyqlQuery).
All four generated report queries were executed against the connected Mirai
store; the GraphQL wrapper passed Shopify's schema validator.

## Runtime

`GET /attribution-api?start=YYYY-MM-DD&end=YYYY-MM-DD&comparison=previous`
requires a bearer session verified with Mirai's existing `/auth/me`. Responses
are `no-store`; credentials and raw upstream errors never reach the browser.
Only aggregated records are returned. There are no order/customer identifiers.

The service reuses `SHOPIFY_STORE` and `SHOPIFY_ACCESS_TOKEN` and the existing
ShopifyQL configuration `SHOPIFYQL_API_VERSION` (default `unstable`, matching
the Shop Campaigns reporting integration). The app needs `read_reports`.
No new permissions or secrets are created. Data is cached in bounded server
memory for five minutes, with request coalescing; nothing is stored in browser
storage, committed, or served from a public static report.

The production server mounts the authenticated router directly, independent of
SEO cache readiness. The preview API below binds only to loopback and is never
imported by the production server.

```sh
npm ci
MIRAI_ATTRIBUTION_ENV=/absolute/path/to/existing/mirai.env npm run attribution:dev
npm run dev -- --host 127.0.0.1 --port 5110
npm run test:attribution
npm run test:seo
npm run build
```

Open `http://127.0.0.1:5110/Attribution`. Development uses the established local
dev sign-in; production always uses Mirai authentication. Node 22+ is supported.

## Verification and release

Tests cover date validation, equal comparison windows, weighted conversion,
reversals, returning orders, both hierarchies, joint filters, previous-only
groups, unallocated residuals, null denominators, CSV injection, upstream
failures, bounded caching and unauthenticated access. They also lock Shop
sales-channel rows as order-only (`n/a` sessions, `—` conversion) and keep
`shop_app` / `shop_campaigns` sessions off the Shop row. Browser QA covers desktop
and 390px mobile, flags, nested expansion, both groupings, filters and downloads.

Deploy through the dashboard's existing build/start workflow. Verify the new
endpoint returns 401 without authentication and opens after Mirai sign-in.
No database migration is required. Roll back the application commit to remove
the report; no Shopify state is modified.
