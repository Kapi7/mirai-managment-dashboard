# Gmail API Setup Guide

This guide will help you set up Gmail API access to read emails from order@korealy.

## Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Click **"New Project"**
3. Name: `Mirai Management Dashboard`
4. Click **"Create"**

## Step 2: Enable Gmail API

1. In your project, go to **APIs & Services** → **Library**
2. Search for **"Gmail API"**
3. Click on it and click **"Enable"**

## Step 3: Create OAuth 2.0 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **"Create Credentials"** → **"OAuth client ID"**

3. If prompted to configure OAuth consent screen:
   - User Type: **External** (or Internal if you have Google Workspace)
   - App name: `Mirai Management Dashboard`
   - User support email: Your email
   - Developer contact: Your email
   - Click **"Save and Continue"**
   - Scopes: Click **"Add or Remove Scopes"**
     - Add: `https://www.googleapis.com/auth/gmail.readonly`
   - Click **"Save and Continue"**
   - Test users: Add your support email address
   - Click **"Save and Continue"**

4. Back to Create OAuth client ID:
   - Application type: **Web application**
   - Name: `Mirai Backend`
   - Authorized redirect URIs:
     - Add: `http://localhost:3001/auth/google/callback`
     - Add: `https://your-app-name.onrender.com/auth/google/callback` (for production)
   - Click **"Create"**

5. **Save these credentials:**
   - Client ID → Copy to `.env` as `GMAIL_CLIENT_ID`
   - Client Secret → Copy to `.env` as `GMAIL_CLIENT_SECRET`

## Step 4: Get Refresh Token

We need to get a refresh token to access Gmail without manual login each time.

### Option A: Use OAuth Playground (Easiest)

1. Go to [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/)

2. Click the **Settings icon** (⚙️) in top right

3. Check **"Use your own OAuth credentials"**
   - OAuth Client ID: Paste your Client ID
   - OAuth Client Secret: Paste your Client Secret

4. In the left sidebar:
   - Find **"Gmail API v1"**
   - Check: `https://www.googleapis.com/auth/gmail.readonly`
   - Click **"Authorize APIs"**

5. Sign in with your **support Gmail account** (the one that receives emails from order@korealy)

6. Click **"Allow"**

7. Click **"Exchange authorization code for tokens"**

8. Copy the **Refresh token** → Save to `.env` as `GMAIL_REFRESH_TOKEN`

### Option B: Manual Script (Alternative)

Create a file `get-gmail-token.js`:

```javascript
import { google } from 'googleapis';
import http from 'http';
import { URL } from 'url';

const CLIENT_ID = 'your_client_id';
const CLIENT_SECRET = 'your_client_secret';
const REDIRECT_URI = 'http://localhost:3001/auth/google/callback';

const oauth2Client = new google.auth.OAuth2(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI);

const scopes = ['https://www.googleapis.com/auth/gmail.readonly'];

const authUrl = oauth2Client.generateAuthUrl({
  access_type: 'offline',
  scope: scopes,
  prompt: 'consent'
});

console.log('Authorize this app by visiting:', authUrl);

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:3001`);
  if (url.pathname === '/auth/google/callback') {
    const code = url.searchParams.get('code');
    const { tokens } = await oauth2Client.getToken(code);
    console.log('\n\nRefresh Token:', tokens.refresh_token);
    res.end('Authentication successful! Check your terminal.');
    server.close();
  }
}).listen(3001);
```

Run: `node get-gmail-token.js`

## Step 5: Update .env File

Your `.env` should now have:

```env
GMAIL_CLIENT_ID=1234567890-abcdefghijklmnop.apps.googleusercontent.com
GMAIL_CLIENT_SECRET=GOCSPX-abcd1234efgh5678
GMAIL_REDIRECT_URI=http://localhost:3001/auth/google/callback
GMAIL_REFRESH_TOKEN=1//0abcdefghijklmnopqrstuvwxyz...
GMAIL_USER_EMAIL=support@yourcompany.com
```

## Step 6: Test Connection

```bash
cd server
npm install
npm start
```

In another terminal:
```bash
curl http://localhost:3001/api/fetch-korealy-emails
```

You should see emails from order@korealy!

## Troubleshooting

### "Invalid grant" error
- Your refresh token expired or was revoked
- Go back to OAuth Playground and generate a new one
- Make sure to click "Revoke access" first if retrying

### "Access blocked: This app's request is invalid"
- Check that your redirect URI matches exactly
- Make sure Gmail API is enabled
- Verify your OAuth consent screen is configured

### No emails returned
- Make sure your support email actually receives emails from order@korealy
- Check the Gmail search query in `server/index.js` (currently: `from:order@korealy subject:shipped`)
- Try testing the query directly in Gmail to verify emails exist

## Production Deployment

When deploying to Render:
1. Add the production callback URL to Google Cloud OAuth credentials
2. Set all environment variables in Render dashboard
3. Keep refresh token secure - never commit to git
