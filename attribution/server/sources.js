// Exact aliases only: similar-looking domains are not attribution evidence.
const providers = [
  ['ChatGPT', ['chatgpt', 'chat gpt', 'chatgpt.com', 'chat.openai.com'], true],
  ['Claude', ['claude', 'claude.ai'], true],
  ['Gemini', ['gemini', 'gemini.google.com', 'bard.google.com'], true],
  ['Perplexity', ['perplexity', 'perplexity.ai'], true],
  ['Copilot', ['copilot', 'copilot.microsoft.com'], true],
  ['Google', ['google', 'google.com']],
  ['Bing', ['bing', 'bing.com']],
  ['Facebook', ['facebook', 'facebook.com', 'm.facebook.com', 'l.facebook.com', 'lm.facebook.com']],
  ['Instagram', ['instagram', 'instagram.com', 'l.instagram.com']],
  ['TikTok', ['tiktok', 'tiktok.com', 'm.tiktok.com']],
  ['YouTube', ['youtube', 'youtube.com', 'm.youtube.com', 'youtu.be']],
  ['Pinterest', ['pinterest', 'pinterest.com']],
  ['Reddit', ['reddit', 'reddit.com', 'old.reddit.com', 'com.reddit.frontpage']],
  ['DuckDuckGo', ['duckduckgo', 'duckduckgo.com']],
  ['Yahoo', ['yahoo', 'yahoo!', 'yahoo.com', 'search.yahoo.com']],
  ['Brave', ['brave', 'search.brave.com']],
  ['Ecosia', ['ecosia', 'ecosia.org']],
  ['Klaviyo', ['klaviyo']],
  ['Direct', ['direct']],
  ['Shop', ['shop']],
];
const aliases = new Map(providers.flatMap(([name, values, ai = false]) => values.map(value => [value, { name, ai }])));

export function canonicalSource(value) {
  const original = String(value || '').trim();
  let key = original.toLowerCase().replace(/\s+/g, ' ');
  // Referring channels can contain a bare domain or a full referrer URL.
  if (/^(https?:\/\/|\/\/)/.test(key) || /^[a-z0-9.-]+\.[a-z]{2,}(?:[/?#]|$)/.test(key)) {
    try {
      const url = new URL(key.startsWith('//') ? `https:${key}` : /^https?:/.test(key) ? key : `https://${key}`);
      key = url.hostname.replace(/^www\./, '').replace(/\.$/, '');
    } catch { return { name: original, ai: false }; }
    return aliases.get(key) || { name: key, ai: false };
  }
  return aliases.get(key) || { name: original, ai: false };
}
