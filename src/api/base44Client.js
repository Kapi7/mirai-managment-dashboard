import { createClient } from '@base44/sdk';

// Create a client with authentication required
export const base44 = createClient({
  appId: import.meta.env.VITE_BASE44_APP_ID || "691afeab306bf144680a5668",
  requiresAuth: true
});
