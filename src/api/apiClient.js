// API client for Mirai backend
// In production, API is on same domain. In dev, it's on localhost:3001
const API_BASE_URL = import.meta.env.VITE_API_URL || (
  import.meta.env.DEV ? 'http://localhost:3001' : ''
);

export const api = {
  async fetchKorealyEmails() {
    const response = await fetch(`${API_BASE_URL}/api/fetch-korealy-emails`);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Failed to fetch emails');
    }
    return response.json();
  },

  async updateShopifyTracking(orderNumber, trackingNumber, carrier) {
    const response = await fetch(`${API_BASE_URL}/api/update-shopify-tracking`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ orderNumber, trackingNumber, carrier })
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Failed to update tracking');
    }
    return response.json();
  }
};
