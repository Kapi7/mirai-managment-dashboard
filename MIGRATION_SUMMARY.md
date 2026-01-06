# Migration from Base44 to Independent Backend

## What Changed

### Before (Base44)
```
Browser → Base44 SDK → Base44 Cloud → Gmail & Shopify
```
- Required Base44 account
- Authentication redirects
- Limited control
- Vendor lock-in

### After (Independent)
```
Browser → Your Backend API → Gmail & Shopify APIs (Direct)
```
- Fully independent
- No third-party dependencies
- Complete control
- Direct API access

## Files Added

### Backend
- `server/package.json` - Backend dependencies
- `server/index.js` - Express API server with Gmail & Shopify integration

### Frontend Changes
- `src/api/apiClient.js` - New API client (replaces Base44)
- Removed: `src/api/base44Client.js`
- Updated: `src/pages/KorealyProcessor.jsx` - Now calls our backend
- Updated: `src/pages/Layout.jsx` - Removed Base44 auth

### Documentation
- `GMAIL_SETUP.md` - Complete Gmail OAuth setup guide
- `RENDER_DEPLOYMENT.md` - Updated deployment instructions
- `MIGRATION_SUMMARY.md` - This file

### Configuration
- `.env` - Now contains Shopify + Gmail credentials
- `.env.example` - Updated template
- `package.json` - Removed `@base44/sdk` dependency

## API Endpoints

Your backend (`server/index.js`) provides:

### `GET /api/fetch-korealy-emails`
Fetches emails from Gmail with sender:order@korealy

**Returns:**
```json
{
  "pending": [...],  // Emails not yet synced to Shopify
  "all": [...],      // All Korealy emails
  "gmailAccount": "support@example.com"
}
```

### `POST /api/update-shopify-tracking`
Updates Shopify order with tracking number

**Body:**
```json
{
  "orderNumber": "1234",
  "trackingNumber": "ABC123456789",
  "carrier": "Australia Post"
}
```

## Environment Variables

### Frontend (VITE_*)
```env
VITE_API_URL=http://localhost:3001
```

### Backend
```env
# Shopify
SHOPIFY_STORE=9dkd2w-g3.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxx

# Gmail OAuth
GMAIL_CLIENT_ID=xxxxx
GMAIL_CLIENT_SECRET=xxxxx
GMAIL_REFRESH_TOKEN=xxxxx
GMAIL_REDIRECT_URI=http://localhost:3001/auth/google/callback
GMAIL_USER_EMAIL=support@example.com
```

## Next Steps

1. **Setup Gmail OAuth** (see GMAIL_SETUP.md)
   - Create Google Cloud project
   - Enable Gmail API
   - Get OAuth credentials
   - Generate refresh token

2. **Update .env file** with your credentials

3. **Test locally:**
   ```bash
   # Terminal 1 - Backend
   cd server
   npm install
   npm start

   # Terminal 2 - Frontend
   npm install
   npm run dev
   ```

4. **Deploy to Render** (see RENDER_DEPLOYMENT.md)
   - Deploy backend as Web Service
   - Deploy frontend as Static Site
   - Configure environment variables

## Benefits of Independent Backend

✅ **No vendor lock-in** - You own the code
✅ **No authentication redirects** - Direct API access
✅ **Better error handling** - Full control over logic
✅ **Free hosting** - Render free tier for backend
✅ **Easier debugging** - See all code and logs
✅ **Customizable** - Add features anytime

## Support

If you encounter issues:

1. **Gmail errors** - Check GMAIL_SETUP.md
2. **Shopify errors** - Verify store URL and token
3. **Connection errors** - Check VITE_API_URL points to backend
4. **Deployment** - Follow RENDER_DEPLOYMENT.md step by step
