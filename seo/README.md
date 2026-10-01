# Mirai SEO

Marketing → SEO (`/SEO`) runs inside Mirai Management with its existing sign-in.
Mirai Skin is the main store and default selection; Glow Coded and Rooted Glow
are satellites. The Ecosystem scope includes all three.

This ports the Aether SEO reporting engine and family dashboard from `d825602`
plus the scope/date navigation changes through `007cb96`. It uses only the Mirai
registry and credentials, with no Aether properties or cached data.

## What is included

- Search Console daily totals, named queries, pages and country breakdowns.
- GA4 visits, channels, sources, countries and configured outbound click events.
- A traffic-to-sales view with GA4 session source/medium, ecommerce purchases and
  purchase revenue in USD. These are analytics observations, not reconciled
  Shopify paid orders or a cross-domain customer journey.
- Ahrefs authority profiles, country-specific competitor discovery and content
  gaps, guarded by available included units and a monthly research budget.
- Shared scopes, comparison periods, date navigation and clickable chart days.
- Public connection checks for each domain, sitemap, robots.txt and llms.txt.

The Shopify/Cloudflare Pages sites do not use the inherited WordPress connector.
The production-host allowlist is applied to GA4 reports to exclude preview hosts.
Default history is three months, with a seven-day rolling refresh. Search Console
lags three days and GA4 two days. The display ends at the common source date.
Older periods show a partial-history notice. Detailed named-query/page samples are
bounded to 500/250 per site ranked over retained history; daily headline totals
are not sampled. Google can suppress anonymized queries.

## Server configuration

Use Node 22.22.0 or a compatible Node 22 release (`better-sqlite3` is native).
The normal `./build.sh` installs the root and server dependencies. The existing
Render start command and reports supervisor remain the same.

| Variable | Purpose |
| --- | --- |
| `MIRAI_SEO_GOOGLE_TOKEN_PATH` | Absolute path to the Mirai OAuth JSON secret; default `/etc/secrets/mirai-seo-google.json` |
| `MIRAI_SEO_AHREFS_TOKEN_PATH` | Absolute path to the Ahrefs key file; default `/etc/secrets/mirai-ahrefs-token` |
| `MIRAI_SEO_AHREFS_API_KEY` | Alternative to the Ahrefs secret file |
| `MIRAI_SEO_AUTO_REFRESH` | Set `1` to check hourly and refresh Google when the last successful run is over 24 hours old |
| `MIRAI_SEO_DATABASE_PATH` | Optional local SQLite path; default `seo/data/mirai-seo.db` |
| `DATABASE_URL` | Existing Mirai Postgres; stores a compressed aggregate-only snapshot in `mirai_seo_cache` |
| `MIRAI_SEO_BACKFILL_MONTHS` | Initial/full import range, 1–16; default 3 |
| `MIRAI_SEO_AHREFS_RESEARCH_MONTHLY_UNITS` | Research budget, default 10000; provider allowance also applies |

The Google file may be the existing Python OAuth export: only its client ID,
client secret and refresh token are normalized in memory. The original file is
never modified. A service-account JSON is also supported if it has access to all
three GSC and GA4 properties. Credentials stay server-side, outside Git and builds.

Verified registry:

| Site | Role | Search Console | GA4 property |
| --- | --- | --- | --- |
| mirai-skin.com | Main Shopify store | sc-domain:mirai-skin.com | 475812683 |
| glow-coded.com | Beauty satellite | sc-domain:glow-coded.com | 530345570 |
| rooted-glow.com | Wellness satellite | sc-domain:rooted-glow.com | 530337594 |

## Refresh and persistence

An administrator can click **Refresh Google data**. This never calls paid Ahrefs
endpoints. Ahrefs research/refresh requires a separate explicit dashboard action;
quota checks refuse requests before spending when included allowance is too low.

SQLite serves local reads. With `DATABASE_URL`, a consistent SQLite backup is
compressed and saved atomically in Postgres after each update. Startup restores
missing local history. Mutations take a Postgres advisory lock and restore the
latest shared snapshot before running, so overlapping deployments cannot overwrite
one another's history or run simultaneous research. A failed restore prevents SEO
API access while leaving the main dashboard available. Without `DATABASE_URL`,
use a persistent local disk; ephemeral local-only storage does not survive deploys.

Every SEO API request validates the Mirai bearer session through `/auth/me`.
Only admins may refresh or run research. Responses containing analytics use
`Cache-Control: no-store`. The public HTML shell contains no analytics or secrets.
No credentials are added to query strings, browser messages or exports.

## Development and verification

```sh
npm ci
MIRAI_SEO_GOOGLE_TOKEN_PATH=/absolute/path/to/token.json npm run seo:fetch
npm run seo:dev
npm run dev -- --host 127.0.0.1 --port 5107
npm run test:seo
npm run build
```

The standalone development server binds only to loopback and injects a local
admin for preview. It is not imported by the production router. Vite proxies
`/seo-dashboard` to port 5106 (override `MIRAI_SEO_DEV_URL` when needed).
`npm run seo:fetch -- --full` refreshes the configured full window;
`--ahrefs` explicitly selects Ahrefs profiles.

Tests cover Mirai-only configuration, OAuth normalization, authenticated access,
admin mutation boundaries, commerce host/currency filters and error preservation,
sampled-detail versus complete totals, durable snapshot restore, cross-instance
write exclusion, serialized refresh, quota limits, cached research and scope/date
navigation.

## Deployment checklist and rollback

1. Deploy the reviewed branch with the normal build/start commands on Node 22.
2. Mount the two secret files under the paths above. Enable automatic Google
   refresh after the credentials are present. Keep the existing database and
   reports environment unchanged.
3. Sign in as a Mirai administrator; open Marketing → SEO. Run the first Google
   import if automatic refresh is disabled. Verify all three sites' freshness.
4. Check source health and the real selected date window. Ahrefs may stay
   unavailable until included units are replenished; Google remains independent.
5. Verify `/seo-dashboard/api/dashboard` returns 401 without a bearer token.

Rollback by redeploying the preceding dashboard commit. The new cache table is
isolated and can remain for recovery; existing reports/order tables are untouched.
Do not run an independent CLI writer against the same local SQLite path while
this web process is active. Production updates should use the authenticated UI.
