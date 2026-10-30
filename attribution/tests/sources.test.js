import test from 'node:test';
import assert from 'node:assert/strict';
import { channelFor, normalizeReport, reportRange } from '../server/report.js';
import { buildView, exportCsv, sortRows } from '../../src/features/attribution/model.js';

test('AI names, domains and URLs aggregate without inventing an organic classification', () => {
  for (const source of ['chatgpt', 'Chat GPT', ' CHAT  GPT ', 'chatgpt.com', 'www.chatgpt.com/', 'https://chatgpt.com/search?q=skincare', '//chat.openai.com/']) {
    for (const traffic_type of ['organic', 'unknown', '']) {
      assert.equal(channelFor({ referring_channel: source, traffic_type }), 'ChatGPT');
    }
    assert.equal(channelFor({ referring_channel: source, traffic_type: 'paid' }), 'ChatGPT · Paid');
  }
  for (const [source, expected] of [['claude.ai', 'Claude'], ['gemini.google.com', 'Gemini'], ['perplexity.ai', 'Perplexity'], ['copilot.microsoft.com', 'Copilot']]) {
    assert.equal(channelFor({ referring_channel: source }), expected);
  }
});

test('exact aliases preserve paid/organic, Shop sales channels and unknown sources', () => {
  assert.equal(channelFor({ referring_channel: 'https://www.google.com/', traffic_type: 'organic' }), 'Google · Organic');
  assert.equal(channelFor({ referring_channel: 'l.facebook.com', traffic_type: 'paid' }), 'Facebook · Paid');
  assert.equal(channelFor({ referring_channel: 'www.GLOW-CODED.com/' }), 'glow-coded.com');
  for (const source of ['chatgpt.com.evil.example', 'mychatgpt.com', 'openai.com', 'not-chatgpt', 'shop_app', 'shop_campaigns']) {
    assert.notEqual(channelFor({ referring_channel: source }), 'ChatGPT');
  }
  assert.equal(channelFor({ referring_channel: 'https://chatgpt.com@evil.example' }), 'evil.example');
  assert.equal(channelFor({ referring_channel: 'direct', utm_source: 'google', referrer_domain: 'mirai-skin.com' }), 'Direct');
  assert.equal(channelFor({ referring_channel: null, traffic_type: 'paid' }), 'Unattributed');
  assert.equal(channelFor({ referring_channel: 'chatgpt.com', sales_channel: 'Shop' }, true), 'Shop');
});

test('merged sources reconcile across dates, countries, comparisons, filters and CSV', () => {
  const range = reportRange({ start: '2026-10-23', end: '2026-10-24' }, new Date('2026-10-30'));
  const session = (source, day, code, sessions, converted = 0) => ({ referring_channel: source, traffic_type: source === 'chatgpt' ? 'organic' : 'unknown', day, session_country: code, session_country_code: code, sessions, sessions_that_completed_checkout: converted });
  const rows = normalizeReport([
    session('chatgpt', '2026-10-23', 'US', 10, 1),
    session('chatgpt.com', '2026-10-23', 'US', 2, 1),
    session('Chat GPT', '2026-10-24', 'GB', 5),
    session('chat.openai.com', '2026-10-21', 'US', 4, 1),
    session('direct', '2026-10-23', 'US', 20),
  ], [{ referring_channel: 'chatgpt.com', traffic_type: 'unknown', day: '2026-10-23', shipping_country: 'US', shipping_country_code: 'US', sales_channel: 'Online Store', orders: 2, net_sales: 60, new_or_returning_customer: 'Returning' }], range);
  const report = { rows, range, currency: 'USD', timezone: 'Asia/Jerusalem' };
  assert.equal(buildView(report).current.sessions, 37);
  for (const group of ['channel', 'country']) {
    const view = buildView(report, { channel: 'ChatGPT', group });
    assert.equal(view.current.sessions, 17);
    assert.equal(view.current.orders, 2);
    assert.equal(view.current.returningOrders, 2);
    assert.equal(view.current.amount, 60);
    assert.equal(view.current.conversion, 2 / 17);
    assert.equal(view.previous.sessions, 4);
    assert.equal(view.daily[0].current.sessions, 12);
    const csv = exportCsv(view, report, group);
    assert.equal(csv.split('\r\n').length, 3);
    assert.ok(!csv.includes('chatgpt.com'));
    assert.ok(csv.includes('"ChatGPT"'));
  }
  assert.equal(buildView(report, { channel: 'ChatGPT', country: 'US' }).current.sessions, 12);
  assert.equal(buildView(report, { channel: 'Direct' }).current.sessions, 20);
});

test('numeric sorting works both ways, keeps missing values last and leaves input intact', () => {
  const rows = [
    { label: 'Small', current: { sessions: 2, orders: 1, conversion: 0.5, amount: -10, returningOrders: 1 } },
    { label: 'Large', current: { sessions: 100, orders: 10, conversion: 0.1, amount: 100, returningOrders: 5 } },
    { label: 'Shop', current: { sessions: 0, orders: 3, conversion: null, amount: 20, returningOrders: 2 } },
    { label: 'Zero', current: { sessions: 0, orders: 0, conversion: null, amount: 0, returningOrders: 0 } },
  ];
  assert.deepEqual(sortRows(rows, 'sessions').map(r => r.label), ['Large', 'Small', 'Zero', 'Shop']);
  assert.deepEqual(sortRows(rows, 'sessions', 1).map(r => r.label), ['Zero', 'Small', 'Large', 'Shop']);
  assert.deepEqual(sortRows(rows, 'orders').map(r => r.label), ['Large', 'Shop', 'Small', 'Zero']);
  assert.deepEqual(sortRows(rows, 'conversion').map(r => r.label), ['Small', 'Large', 'Shop', 'Zero']);
  assert.equal(sortRows(rows, 'amount', 1)[0].label, 'Small');
  assert.equal(sortRows(rows, 'returningOrders')[0].label, 'Large');
  assert.deepEqual(rows.map(r => r.label), ['Small', 'Large', 'Shop', 'Zero']);
});
