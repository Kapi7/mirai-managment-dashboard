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

// Reports API endpoint - returns mock data for now
// TODO: Connect to real data source when ready
app.post('/reports-api/daily-report', async (req, res) => {
  try {
    const { start_date, end_date } = req.body;
    console.log(`📊 Generating report: ${start_date} to ${end_date}`);

    // Generate mock daily data
    const start = new Date(start_date);
    const end = new Date(end_date);
    const data = [];

    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
      const dateStr = d.toISOString().split('T')[0];

      // Generate realistic-looking numbers
      const orders = Math.floor(Math.random() * 20) + 5;
      const aov = Math.floor(Math.random() * 50) + 80;
      const net = orders * aov;
      const adSpend = Math.floor(Math.random() * 200) + 100;
      const cogs = net * 0.35;
      const profit = net - cogs - adSpend;

      data.push({
        date: dateStr,
        label: d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }),
        orders: orders,
        gross: Math.round(net * 1.05),
        discounts: Math.round(net * 0.03),
        refunds: Math.round(net * 0.02),
        net: Math.round(net),
        cogs: Math.round(cogs),
        shipping_charged: Math.round(orders * 8),
        shipping_cost: Math.round(orders * 5),
        google_spend: Math.round(adSpend * 0.6),
        meta_spend: Math.round(adSpend * 0.4),
        total_spend: Math.round(adSpend),
        google_pur: Math.floor(orders * 0.6),
        meta_pur: Math.floor(orders * 0.4),
        google_cpa: Math.round((adSpend * 0.6) / (orders * 0.6)),
        meta_cpa: Math.round((adSpend * 0.4) / (orders * 0.4)),
        general_cpa: Math.round(adSpend / orders),
        psp_usd: Math.round(net * 0.029),
        operational_profit: Math.round(profit),
        net_margin: Math.round(profit),
        margin_pct: Number(((profit / net) * 100).toFixed(2)), // Return as number, not string
        aov: Math.round(aov),
        returning_customers: Math.floor(orders * 0.2)
      });
    }

    console.log(`✅ Generated ${data.length} days of data`);
    res.json({ data });
  } catch (error) {
    console.error('❌ Report generation error:', error);
    res.status(500).json({ error: error.message, data: [] });
  }
});

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
  // Extract order number from subject: "A shipment from order #1907 is on the way"
  const orderMatch = subject.match(/order #(\d+)/i);
  const orderNumber = orderMatch ? orderMatch[1] : null;

  // Extract carrier and tracking number from patterns like:
  // "GOFO tracking number: GFUS01028388781186"
  // "Australia Post tracking number: 1234567890123456789012"
  let trackingNumber = null;
  let carrier = null;

  // Try to extract carrier name + tracking number
  const trackingMatch = body.match(/([A-Za-z\s]+)\s+tracking number:\s*([A-Z0-9]{10,})/i);

  if (trackingMatch) {
    carrier = trackingMatch[1].trim();
    trackingNumber = trackingMatch[2];
  } else {
    // Try generic tracking number pattern without carrier
    const genericMatch = body.match(/tracking number:\s*([A-Z0-9]{10,})/i);
    if (genericMatch) {
      trackingNumber = genericMatch[1];
    } else {
      // Try Australia Post pattern (numbers only, 20+ digits)
      const ausPostMatch = body.match(/(\d{20,})/);
      if (ausPostMatch) {
        trackingNumber = ausPostMatch[1];
      }
    }
  }

  return { orderNumber, trackingNumber, carrier };
}

// API: Fetch Korealy emails from Gmail
app.get('/api/fetch-korealy-emails', async (req, res) => {
  try {
    // Search for emails from order@korealy.co
    const response = await gmail.users.messages.list({
      userId: 'me',
      q: 'from:order@korealy.co',
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
        carrier: parsed.carrier || 'N/A',
        shopifyTracking,
        _debug: !parsed.orderNumber || !parsed.trackingNumber // Flag for debugging
      });
    }

    // Filter out N/A orders completely (invalid parsing)
    const validEmails = emails.filter(e =>
      e.orderNumber !== 'N/A' &&
      e.korealyTracking !== 'N/A'
    );

    // Pending = has Korealy tracking but NO Shopify tracking
    const pending = validEmails.filter(e => !e.shopifyTracking);

    console.log(`📧 Fetched ${emails.length} total emails from Gmail`);
    console.log(`✅ ${validEmails.length} valid orders (filtered out N/A)`);
    console.log(`📦 ${pending.length} pending shipments need syncing to Shopify`);
    console.log(`✔️  ${validEmails.filter(e => e.shopifyTracking).length} already synced to Shopify`);

    res.json({
      pending,
      all: validEmails,
      gmailAccount: process.env.GMAIL_USER_EMAIL || 'Connected',
      stats: {
        total: validEmails.length,
        pending: pending.length,
        synced: validEmails.filter(e => e.shopifyTracking).length,
        invalid: emails.length - validEmails.length
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

    console.log(`📦 Updating order #${orderNumber} with tracking: ${trackingNumber}`);

    if (!orderNumber || !trackingNumber) {
      return res.status(400).json({ error: 'Missing orderNumber or trackingNumber' });
    }

    // Find order in Shopify
    const order = await fetchShopifyOrder(orderNumber);

    if (!order) {
      return res.status(404).json({ error: `Order #${orderNumber} not found in Shopify` });
    }

    console.log(`✓ Found Shopify order ID: ${order.id}, fulfillment_status: ${order.fulfillment_status}`);

    // Check if order already has a fulfillment
    const existingFulfillment = order.fulfillments?.[0];

    if (existingFulfillment) {
      console.log(`📝 Updating existing fulfillment ID: ${existingFulfillment.id}`);

      // Update existing fulfillment's tracking
      const updateResponse = await fetch(
        `https://${shopify.store}/admin/api/${shopify.apiVersion}/fulfillments/${existingFulfillment.id}/update_tracking.json`,
        {
          method: 'POST',
          headers: {
            'X-Shopify-Access-Token': shopify.accessToken,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            fulfillment: {
              tracking_number: trackingNumber,
              tracking_company: carrier || 'Australia Post',
              notify_customer: true
            }
          })
        }
      );

      if (!updateResponse.ok) {
        let errorMessage = 'Failed to update fulfillment tracking';
        try {
          const errorData = await updateResponse.json();
          errorMessage = JSON.stringify(errorData.errors || errorData);
          console.error('Shopify API error:', errorData);
        } catch (e) {
          errorMessage = `Shopify API error: ${updateResponse.status} ${updateResponse.statusText}`;
          console.error(errorMessage);
        }
        return res.status(500).json({ error: errorMessage });
      }

      const result = await updateResponse.json();
      console.log(`✅ Successfully updated tracking for order #${orderNumber}`);

      return res.json({
        success: true,
        fulfillment: result.fulfillment,
        action: 'updated'
      });
    }

    // No existing fulfillment - create one with tracking using FulfillmentOrder API
    console.log(`📦 Creating new fulfillment with tracking for order #${orderNumber}`);
    console.log(`Order status: ${order.financial_status}, fulfillment_status: ${order.fulfillment_status}`);

    // Step 1: Get fulfillment orders for this order
    console.log(`🔍 Fetching fulfillment orders for order #${orderNumber}`);
    const fulfillmentOrdersResponse = await fetch(
      `https://${shopify.store}/admin/api/${shopify.apiVersion}/orders/${order.id}/fulfillment_orders.json`,
      {
        headers: {
          'X-Shopify-Access-Token': shopify.accessToken,
          'Content-Type': 'application/json'
        }
      }
    );

    if (!fulfillmentOrdersResponse.ok) {
      console.error(`❌ Failed to fetch fulfillment orders`);
      return res.status(500).json({ error: 'Failed to fetch fulfillment orders from Shopify' });
    }

    const fulfillmentOrdersData = await fulfillmentOrdersResponse.json();
    const fulfillmentOrder = fulfillmentOrdersData.fulfillment_orders?.[0];

    if (!fulfillmentOrder) {
      console.error(`❌ No fulfillment orders found for order #${orderNumber}`);
      return res.status(400).json({ error: 'No fulfillment orders available for this order' });
    }

    console.log(`✓ Found fulfillment order ID: ${fulfillmentOrder.id}, status: ${fulfillmentOrder.status}`);

    // Step 2: Build line items for fulfillment
    const lineItemsToFulfill = fulfillmentOrder.line_items
      .filter(item => item.fulfillable_quantity > 0)
      .map(item => ({
        id: item.id,
        quantity: item.fulfillable_quantity
      }));

    if (lineItemsToFulfill.length === 0) {
      console.log(`❌ No fulfillable items in fulfillment order`);
      return res.status(400).json({
        error: `Order #${orderNumber} has no items that can be fulfilled.`
      });
    }

    console.log(`Found ${lineItemsToFulfill.length} fulfillable items in fulfillment order`);

    // Step 3: Create fulfillment using the modern FulfillmentOrder API
    const fulfillmentData = {
      fulfillment: {
        line_items_by_fulfillment_order: [
          {
            fulfillment_order_id: fulfillmentOrder.id,
            fulfillment_order_line_items: lineItemsToFulfill
          }
        ],
        tracking_info: {
          number: trackingNumber,
          company: carrier || 'Australia Post',
          url: null
        },
        notify_customer: true
      }
    };

    console.log('Fulfillment request:', JSON.stringify(fulfillmentData, null, 2));

    const fulfillmentResponse = await fetch(
      `https://${shopify.store}/admin/api/${shopify.apiVersion}/fulfillments.json`,
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
      let errorMessage = 'Failed to create fulfillment';
      let fullError = null;
      try {
        const errorData = await fulfillmentResponse.json();
        fullError = errorData;
        errorMessage = JSON.stringify(errorData.errors || errorData);
        console.error('❌ Shopify API full error response:', JSON.stringify(errorData, null, 2));
      } catch (e) {
        errorMessage = `Shopify API error: ${fulfillmentResponse.status} ${fulfillmentResponse.statusText}`;
        console.error(errorMessage);
      }
      return res.status(500).json({
        error: errorMessage,
        shopifyError: fullError
      });
    }

    const result = await fulfillmentResponse.json();
    console.log(`✅ Successfully created fulfillment for order #${orderNumber}`);

    res.json({
      success: true,
      fulfillment: result.fulfillment,
      action: 'created'
    });

  } catch (error) {
    console.error('Shopify update error:', error);
    res.status(500).json({ error: error.message || 'Unknown error occurred' });
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

// API: Remove tracking from Shopify (Undo)
app.post('/api/remove-shopify-tracking', async (req, res) => {
  try {
    const { orderNumber } = req.body;

    if (!orderNumber) {
      return res.status(400).json({ error: 'Missing orderNumber' });
    }

    // Find order in Shopify
    const order = await fetchShopifyOrder(orderNumber);

    if (!order) {
      return res.status(404).json({ error: `Order #${orderNumber} not found in Shopify` });
    }

    // Find the fulfillment to cancel
    const fulfillment = order.fulfillments?.[0];

    if (!fulfillment) {
      return res.status(404).json({ error: `No fulfillment found for order #${orderNumber}` });
    }

    // Cancel the fulfillment
    const cancelResponse = await fetch(
      `https://${shopify.store}/admin/api/${shopify.apiVersion}/orders/${order.id}/fulfillments/${fulfillment.id}/cancel.json`,
      {
        method: 'POST',
        headers: {
          'X-Shopify-Access-Token': shopify.accessToken,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({})
      }
    );

    if (!cancelResponse.ok) {
      const errorData = await cancelResponse.json();
      throw new Error(errorData.errors || 'Failed to cancel fulfillment');
    }

    res.json({
      success: true,
      message: `Tracking removed for order #${orderNumber}`
    });

  } catch (error) {
    console.error('Remove tracking error:', error);
    res.status(500).json({ error: error.message });
  }
});

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
