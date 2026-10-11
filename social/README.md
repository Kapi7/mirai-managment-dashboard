# Mirai Social dashboard

Marketing → Social (`/SocialMedia`) opens a Figura-style report in Mirai colours.
The existing social creation, review, scheduling and account tools remain at
`/SocialTools`, linked from the header. Existing permissions are preserved.

The report includes Overview, Channels, Posts, Traffic & sales, Connections,
date/channel/search filters, ranking, export and private connection notes.

## Data and refresh

The repository contains public profile configuration only, with no measurements.
Native metrics are imported into the authenticated dashboard's private cache.
A report reconciles the existing cloud measurement artifact with newer dated
native checks across Instagram, Facebook, YouTube, TikTok, Pinterest and X.
It is the recorded relaunch library, not every historical account post.
Publication dates fall back to confirmation dates only when the source has no
publication timestamp; those rows are labelled. No customer or order records,
credentials or comment contents are included in the packages or exports.
Never commit a populated report to this public source repository.

**Native data is imported, not automatically fetched by this dashboard.**
Instagram, Facebook, YouTube and X values were collected by the existing cloud
workflow; TikTok and Pinterest use original dated manual observations. Profile
links and team verification notes are not OAuth/analytics connections.

Refresh reloads the saved native package. For an administrator it also starts
the existing Google refresh and polls its completion. This does not publish
posts, trigger the legacy AI agents, spend Ahrefs units or change ad budgets.

GA4 traffic and commerce read the existing private SEO cache, scoped to
`mirai-skin` and property `475812683`; satellites are excluded. Recognized social
source aliases/domains are matched exactly. The default report includes paid
and organic; Traffic & sales can separate them. Revenue is GA4 purchase revenue
in USD, not Shopify net collections. Missing days/counters are null, not zero.
Website charts contain gaps for missing source data. Coverage for traffic and
commerce is measured separately. Shopify campaign results retain their own
fixed snapshot window and are not falsely filtered into different dates.

To update native data:

```sh
gh run download RUN_ID --repo Kapi7/mirai-meta-campaign -n mirai-measurement -D /tmp/mirai-measurement
python3 social/scripts/import-measurement.py /tmp/mirai-measurement /path/to/local/10-measurement /tmp/mirai-social-package.json
```

In Social → Connections → Import measurement package, paste the resulting JSON.
Only existing Mirai admins can import or update notes. The parser keeps allowed
aggregate fields, rejects unsafe links, invalid post dates and duplicate posts,
and refuses packages older than the saved report. Use the audit directory with
the newest native checks so manual observations are preserved by the importer.

State is stored in an isolated `mirai_social_state` table inside the existing
SEO cache. It uses the runtime's serialized writer and durable storage, including
Mirai's production `/data` disk. Concurrent updates require a matching revision.

## Validation and release

```sh
npm run test:social
npm run test:seo
npm run build
```

The local SEO dev entry point is loopback-only and already supplies a local admin.
Production routes reuse Mirai's server-side bearer-session verification, no-store
responses and admin mutation checks. No new permissions, credentials or services
are required. Deploy the dashboard normally; rollback to the previous commit
restores the old Social page. The additive state table can remain for recovery.
