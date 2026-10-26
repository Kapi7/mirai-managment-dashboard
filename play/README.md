# App / Play report

`/Play` is the Android performance page in Mirai management. It is separate from Attribution and from the Shopify business report.

The page reads `GET /play-api`. A signed-in session is required in production. When a source is not configured, its metrics stay blank. Zero is shown only when that source reports zero. GA4 `first_open` and `app_remove` are never copied into Play installs or uninstalls.

## Sources

| Metric | Source | Required environment |
| --- | --- | --- |
| Device installs, device uninstalls, US / AU / GB / CA / IL split | Play Console bulk export `installs_<package>_YYYYMM_country.csv` | `PLAY_STATS_BUCKET` **or** `PLAY_STATS_DIR` (not both). A bucket also needs `PLAY_GOOGLE_CREDENTIALS_PATH`. |
| Crash count, ANR count, latest user-perceived rate | Play Developer Reporting API | `PLAY_GOOGLE_CREDENTIALS_PATH` |
| Sessions, range active users, latest-day active users, `first_open`, `app_remove` | GA4 Data API for the Firebase **app** property | `PLAY_GA4_PROPERTY_ID` plus `PLAY_GOOGLE_CREDENTIALS_PATH` or `GOOGLE_APPLICATION_CREDENTIALS` |

`PLAY_PACKAGE_NAME` defaults to `com.miraiskin.mobile`.

`PLAY_STATS_BUCKET` is the bucket name only, without `gs://`. Play Console → Download reports → Copy Cloud Storage URI, then keep the bucket segment.

The service account needs:

- Play Console → Users and permissions, on `com.miraiskin.mobile`
- Play Developer Reporting API enabled
- Storage Object Viewer, if a bucket is used
- GA4 Viewer on the Android property, if sessions are used

The SEO OAuth token (`MIRAI_SEO_GOOGLE_TOKEN_PATH`) is not reused. Website property ids `475812683`, `530345570` and `530337594` are rejected so website sessions cannot be shown as app sessions.

Credentials stay on the server. Paths, bucket names and access tokens are not returned to the browser.

## Local check

```sh
npm run test:play
npm run play:dev
npm run dev
```

Open `http://127.0.0.1:3000/Play`. With no Play env vars, the page shows the empty state. `play:dev` listens on `127.0.0.1:5111` and skips Mirai sign-in; it is not used in production. Production mounts `/play-api` on the existing Node server and uses the same session check as Attribution.

To preview with a local export, set `PLAY_STATS_DIR` to a directory that contains `installs_com.miraiskin.mobile_YYYYMM_country.csv` and point `MIRAI_PLAY_ENV` at that env file before `npm run play:dev`.

## Ship

This page does not change ads, the Play listing, or Render by itself. A production deploy has to merge and start the dashboard, then set the env vars above. Until those vars exist, the live page stays empty.
