# Android Play performance — for Mirai Skin

Draft only. This does not merge to main, does not deploy Render, and does not change ads or the Play listing.

## What exists now

Business Reports (`/Reports`) are Shopify reports: daily orders, net revenue, Google / Meta / Shop ad spend, profit, orders, and best sellers. Attribution (`/Attribution`) is Shopify session and sales attribution. SEO and Social read website GA4 properties:

- mirai-skin.com `475812683`
- glow-coded.com `530345570`
- rooted-glow.com `530337594`

Those properties are websites. They are not the Android app.

Checked in this repository on 2026-10-26: no Play Console client, no Play Developer Reporting calls, no Firebase, Crashlytics, or Expo project, and no `google-services` file. `.env.development` only names `VITE_API_URL` and `VITE_REPORT_API_URL`. No app metric credentials are stored here.

Unauthenticated check of https://mirai-managment-dashboard.onrender.com on 2026-10-26:

- `/health` returned 200
- `/attribution-api` returned 401
- `/play-api` returned the HTML app shell, so the live service had no Play JSON route

Play 1.0.0 live PASS was reported by Mirai Skin. This dashboard does not read the store listing and does not confirm that status.

## Report surface

New Analytics page **App / Play** (`/Play`), also linked from Business Reports. Attribution is unchanged.

Each metric stays blank until its own source answers. Blank is not zero.

- Installs and uninstalls: Play Console country export (`installs_com.miraiskin.mobile_YYYYMM_country.csv`), daily device counts
- Crashes and ANRs: Play Developer Reporting `errorReportCount` for `CRASH` and `ANR`, plus the latest daily user-perceived rate when that call succeeds. Counts are app-wide. The error count metric set has no country dimension, so country crash and ANR cells stay blank.
- Sessions, range active users, and latest-day active users: GA4 property named by `PLAY_GA4_PROPERTY_ID`
- Country rows: US, AU, GB, CA, IL, plus other countries that were actually present
- GA4 `first_open` and `app_remove` are shown in their own columns and are never copied into Play installs or uninstalls

## Blockers

No secret values belong in git. Set these on the server that runs the dashboard:

1. **Play installs and uninstalls.** `PLAY_STATS_BUCKET` (Play Console → Download reports → Cloud Storage bucket name, without `gs://`) or `PLAY_STATS_DIR` (a directory of the country CSV files). Set only one. A bucket also needs `PLAY_GOOGLE_CREDENTIALS_PATH`. Play Developer Reporting does not provide install or uninstall counts.
2. **Crashes and ANRs.** `PLAY_GOOGLE_CREDENTIALS_PATH` must point at a service-account JSON key. Enable the Play Developer Reporting API and invite that account in Play Console → Users and permissions for `com.miraiskin.mobile`. The SEO OAuth token is not reused.
3. **Sessions and active users.** `PLAY_GA4_PROPERTY_ID` must be the Firebase-linked GA4 property for the Android app. Also set `PLAY_GOOGLE_CREDENTIALS_PATH` or `GOOGLE_APPLICATION_CREDENTIALS` to a service account with Viewer on that property. The website ids above are rejected.
4. **Package id.** `PLAY_PACKAGE_NAME` is optional. The default is `com.miraiskin.mobile`.

This repository does not contain the Expo app, so custom in-app event names were not verified. Mirai Mobile is needed only if Skin wants events beyond GA4’s automatic `session_start`, `first_open` and `app_remove`. Day-1 sessions and active users do not need an app release once the app property and key exist.

## Ship

Itay Go and Mirai QA are required before this is on the live dashboard. After a merge, Render needs the env vars above or the page stays empty. Do not deploy this draft as part of opening the pull request.
