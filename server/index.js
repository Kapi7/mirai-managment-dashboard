import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import { google } from 'googleapis';
import Shopify from '@shopify/shopify-api';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: '../.env' });

const app = express();
const PORT = process.env.PORT || 3001;

// Middleware
app.use(cors());
app.use(express.json());

// Gmail OAuth2 setup
const oauth2Client = new google.auth.OAuth2(
  process.env.GMAIL_CLIENT_ID,
  process.env.GMAIL_CLIENT_SECRET,
  process.env.GMAIL_REDIRECT_URI
);

// Set credentials if refresh token is available
if (process.env.GMAIL_REFRESH_TOKEN) {
  oauth2Client.setCredentials({
    refresh_token: process.env.GMAIL_REFRESH_TOKEN
  });
}

const gmail = google.gmail({ version: 'v1', auth: oauth2Client });

// Shopify setup
const shopify = {
  store: process.env.SHOPIFY_STORE,
  accessToken: process.env.SHOPIFY_ACCESS_TOKEN,
  apiVersion: '2024-01'
};

// Helper: Parse Korealy email for tracking info
function parseKorealyEmail(subject, body) {
  // Extract order number from subject: "Order #1234 has been shipped"
  const orderMatch = subject.match(/Order #(\d+)/i);
  const orderNumber = orderMatch ? orderMatch[1] : null;

  // Extract tracking number - common patterns
  const trackingPatterns = [
    /tracking\s*(?:number|#)?\s*:?\s*([A-Z0-9]{10,})/i,
    /tracking\s*code\s*:?\s*([A-Z0-9]{10,})/i,
    /([A-Z0-9]{13,})/  // Generic alphanumeric tracking
  ];

  let trackingNumber = null;
  for (const pattern of trackingPatterns) {
    const match = body.match(pattern);
    if (match) {
      trackingNumber = match[1];
      break;
    }
  }

  // Extract carrier
  const carriers = ['Australia Post', 'AusPost', 'DHL', 'FedEx', 'UPS'];
  let carrier = 'Australia Post'; // default
  for (const c of carriers) {
    if (body.toLowerCase().includes(c.toLowerCase())) {
      carrier = c;
      break;
    }
  }

  return { orderNumber, trackingNumber, carrier };
}

// API: Fetch Korealy emails from Gmail
app.get('/api/fetch-korealy-emails', async (req, res) => {
  try {
    // Search for emails from order@korealy
    // Search for any emails from order@korealy (remove subject filter to get all)
    const response = await gmail.users.messages.list({
      userId: 'me',
      q: 'from:order@korealy',
      maxResults: 100
    });

    const messages = response.data.messages || [];
    const emails = [];

    // Fetch full message details
    for (const message of messages) {
      const msg = await gmail.users.messages.get({
        userId: 'me',
        id: message.id,
        format: 'full'
      });

      const headers = msg.data.payload.headers;
      const subject = headers.find(h => h.name === 'Subject')?.value || '';
      const date = headers.find(h => h.name === 'Date')?.value || '';

      // Get body
      let body = '';
      if (msg.data.payload.body.data) {
        body = Buffer.from(msg.data.payload.body.data, 'base64').toString();
      } else if (msg.data.payload.parts) {
        const textPart = msg.data.payload.parts.find(p => p.mimeType === 'text/plain');
        if (textPart?.body?.data) {
          body = Buffer.from(textPart.body.data, 'base64').toString();
        }
      }

      const parsed = parseKorealyEmail(subject, body);

      // Show ALL emails from Korealy, even if parsing fails
      // This helps with debugging and shows history
      let shopifyTracking = null;

      // Only check Shopify if we have a valid order number
      if (parsed.orderNumber) {
        try {
          const shopifyOrder = await fetchShopifyOrder(parsed.orderNumber);
          shopifyTracking = shopifyOrder?.fulfillments?.[0]?.tracking_number || null;
        } catch (err) {
          console.log(`Order #${parsed.orderNumber} not found in Shopify`);
        }
      }

      // Add email to list (even if parsing was incomplete)
      emails.push({
        id: message.id,
        subject,
        date: new Date(date).toISOString(),
        body: body.substring(0, 500), // First 500 chars for preview
        orderNumber: parsed.orderNumber || 'N/A',
        korealyTracking: parsed.trackingNumber || 'N/A',
        carrier: parsed.carrier || 'Unknown',
        shopifyTracking,
        _debug: !parsed.orderNumber || !parsed.trackingNumber // Flag for debugging
      });
    }

    // Separate pending (no Shopify tracking AND has valid tracking number) from all
    const pending = emails.filter(e =>
      !e.shopifyTracking &&
      e.korealyTracking !== 'N/A' &&
      e.orderNumber !== 'N/A'
    );

    console.log(`📧 Fetched ${emails.length} emails from Gmail`);
    console.log(`📦 ${pending.length} pending shipments need updating`);
    console.log(`✅ ${emails.filter(e => e.shopifyTracking).length} already synced to Shopify`);

    res.json({
      pending,
      all: emails,
      gmailAccount: process.env.GMAIL_USER_EMAIL || 'Connected',
      stats: {
        total: emails.length,
        pending: pending.length,
        synced: emails.filter(e => e.shopifyTracking).length,
        needsParsing: emails.filter(e => e._debug).length
      }
    });

  } catch (error) {
    console.error('Gmail fetch error:', error);
    res.status(500).json({ error: error.message });
  }
});

// API: Update Shopify order with tracking
app.post('/api/update-shopify-tracking', async (req, res) => {
  try {
    const { orderNumber, trackingNumber, carrier } = req.body;

    if (!orderNumber || !trackingNumber) {
      return res.status(400).json({ error: 'Missing orderNumber or trackingNumber' });
    }

    // Find order in Shopify
    const order = await fetchShopifyOrder(orderNumber);

    if (!order) {
      return res.status(404).json({ error: `Order #${orderNumber} not found in Shopify` });
    }

    // Create fulfillment with tracking
    const fulfillmentData = {
      fulfillment: {
        location_id: order.location_id,
        tracking_number: trackingNumber,
        tracking_company: carrier || 'Australia Post',
        notify_customer: true,
        line_items: order.line_items.map(item => ({
          id: item.id,
          quantity: item.quantity
        }))
      }
    };

    const fulfillmentResponse = await fetch(
      `https://${shopify.store}/admin/api/${shopify.apiVersion}/orders/${order.id}/fulfillments.json`,
      {
        method: 'POST',
        headers: {
          'X-Shopify-Access-Token': shopify.accessToken,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(fulfillmentData)
      }
    );

    if (!fulfillmentResponse.ok) {
      const errorData = await fulfillmentResponse.json();
      throw new Error(errorData.errors || 'Failed to create fulfillment');
    }

    const result = await fulfillmentResponse.json();

    res.json({
      success: true,
      fulfillment: result.fulfillment
    });

  } catch (error) {
    console.error('Shopify update error:', error);
    res.status(500).json({ error: error.message });
  }
});

// Helper: Fetch Shopify order by order number
async function fetchShopifyOrder(orderNumber) {
  const response = await fetch(
    `https://${shopify.store}/admin/api/${shopify.apiVersion}/orders.json?name=%23${orderNumber}`,
    {
      headers: {
        'X-Shopify-Access-Token': shopify.accessToken,
        'Content-Type': 'application/json'
      }
    }
  );

  if (!response.ok) {
    throw new Error('Failed to fetch Shopify order');
  }

  const data = await response.json();
  return data.orders?.[0] || null;
}

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Serve static files from the React app (after API routes)
app.use(express.static(path.join(__dirname, '../dist')));

// Serve React app for all other routes (must be last)
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, '../dist/index.html'));
});

app.listen(PORT, () => {
  console.log(`🚀 Mirai Backend running on port ${PORT}`);
  console.log(`📱 Frontend served at: http://localhost:${PORT}`);
  console.log(`🔌 API available at: http://localhost:${PORT}/api`);
});
