/**
 * Gmail OAuth Setup Script
 *
 * Run this to get a Gmail refresh token for sending emails.
 *
 * Prerequisites:
 * 1. Go to Google Cloud Console (https://console.cloud.google.com/)
 * 2. Create a project or select existing one
 * 3. Enable Gmail API: APIs & Services > Library > Gmail API > Enable
 * 4. Create OAuth credentials: APIs & Services > Credentials > Create Credentials > OAuth client ID
 *    - Application type: Web application
 *    - Authorized redirect URIs: http://localhost:3001/auth/google/callback
 * 5. Copy the Client ID and Client Secret
 *
 * Usage:
 *   GMAIL_CLIENT_ID=xxx GMAIL_CLIENT_SECRET=yyy node scripts/gmail_oauth_setup.js
 */

import { google } from 'googleapis';
import http from 'http';
import { URL } from 'url';
import open from 'open';

const CLIENT_ID = process.env.GMAIL_CLIENT_ID;
const CLIENT_SECRET = process.env.GMAIL_CLIENT_SECRET;
const REDIRECT_URI = 'http://localhost:3001/auth/google/callback';

if (!CLIENT_ID || !CLIENT_SECRET || CLIENT_ID.includes('your_')) {
  console.log(`
╔═══════════════════════════════════════════════════════════════════╗
║                    Gmail OAuth Setup Guide                         ║
╠═══════════════════════════════════════════════════════════════════╣
║                                                                     ║
║  1. Go to: https://console.cloud.google.com/                       ║
║                                                                     ║
║  2. Create or select a project                                     ║
║                                                                     ║
║  3. Enable Gmail API:                                              ║
║     APIs & Services > Library > Search "Gmail API" > Enable        ║
║                                                                     ║
║  4. Configure OAuth consent screen:                                ║
║     APIs & Services > OAuth consent screen                         ║
║     - User Type: External                                          ║
║     - Add your email as a test user                                ║
║                                                                     ║
║  5. Create OAuth credentials:                                      ║
║     APIs & Services > Credentials > Create Credentials             ║
║     - Select: OAuth client ID                                      ║
║     - Application type: Web application                            ║
║     - Authorized redirect URIs:                                    ║
║       http://localhost:3001/auth/google/callback                   ║
║                                                                     ║
║  6. Copy Client ID and Client Secret, then run:                    ║
║                                                                     ║
║     GMAIL_CLIENT_ID=xxx GMAIL_CLIENT_SECRET=yyy \\                  ║
║       node scripts/gmail_oauth_setup.js                            ║
║                                                                     ║
╚═══════════════════════════════════════════════════════════════════╝
`);
  process.exit(1);
}

const oauth2Client = new google.auth.OAuth2(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI);

// Generate auth URL
const authUrl = oauth2Client.generateAuthUrl({
  access_type: 'offline',
  scope: [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly'
  ],
  prompt: 'consent' // Force to get refresh token
});

console.log('\n🔐 Opening browser for Google OAuth...\n');

// Start temporary server to catch the callback
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost:3001');

  if (url.pathname === '/auth/google/callback') {
    const code = url.searchParams.get('code');

    if (code) {
      try {
        const { tokens } = await oauth2Client.getToken(code);

        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(`
          <html>
            <body style="font-family: system-ui; padding: 40px; text-align: center;">
              <h1>✅ Success!</h1>
              <p>You can close this window and check the terminal.</p>
            </body>
          </html>
        `);

        console.log('\n✅ OAuth successful! Add these to your .env file:\n');
        console.log('═'.repeat(60));
        console.log(`GMAIL_CLIENT_ID=${CLIENT_ID}`);
        console.log(`GMAIL_CLIENT_SECRET=${CLIENT_SECRET}`);
        console.log(`GMAIL_REDIRECT_URI=${REDIRECT_URI}`);
        console.log(`GMAIL_REFRESH_TOKEN=${tokens.refresh_token}`);
        console.log('═'.repeat(60));
        console.log('\nThen restart your server!\n');

        server.close();
        process.exit(0);
      } catch (err) {
        res.writeHead(500);
        res.end('Error getting tokens: ' + err.message);
        console.error('Error:', err);
      }
    } else {
      res.writeHead(400);
      res.end('No code received');
    }
  }
});

server.listen(3001, () => {
  console.log('Waiting for OAuth callback on http://localhost:3001...');
  open(authUrl);
});
