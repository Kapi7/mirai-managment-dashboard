import { createRuntime } from './runtime.js';
const runtime = createRuntime();
try {
  const source = process.argv.includes('--ahrefs') ? 'ahrefs' : null;
  await runtime.refresh({ full: process.argv.includes('--full'), ...(source ? { source } : {}) });
  console.log(JSON.stringify(runtime.state));
} catch { console.error(runtime.state.error || runtime.error()); process.exitCode = 1; }
finally { await runtime.close(); }
