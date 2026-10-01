import { readFileSync } from 'node:fs';

// Accept both Google's authorized_user format and the existing Mirai Python
// OAuth export. Never copy, rewrite, or expose the original credential file.
export function readGoogleCredential(filename) {
  const value = JSON.parse(readFileSync(filename, 'utf8'));
  if (value.type === 'service_account') return value;
  if (!value.client_id || !value.client_secret || !value.refresh_token) {
    throw new Error('The Mirai Google credential needs a refresh token.');
  }
  return { type: 'authorized_user', client_id: value.client_id,
    client_secret: value.client_secret, refresh_token: value.refresh_token };
}
