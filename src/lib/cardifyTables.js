/**
 * Legacy-table mobile treatment: stamp each <td> with its column header as
 * data-label so CSS (index.css, <1024px) can restack wide tables into labeled
 * cards — the president-report mobile standard — without rewriting each page.
 *
 * Tables opt out with .m-table (already mobile-handled) — and tables with
 * fewer than 5 columns stay as tables (they fit a phone).
 */
export function cardifyTables(root = document.body) {
  const stamp = (table) => {
    const labels = [...table.querySelectorAll('thead th')].map((th) => th.textContent.trim());
    table.querySelectorAll(':scope > tbody > tr').forEach((tr) => {
      [...tr.children].forEach((td, i) => {
        if (labels[i] && !td.hasAttribute('data-label')) td.setAttribute('data-label', labels[i]);
      });
    });
  };

  root.querySelectorAll('table:not(.m-table):not([data-cardified])').forEach((table) => {
    const cols = table.querySelectorAll('thead th').length;
    if (cols < 5) {
      table.setAttribute('data-cardified', 'skip');
      return;
    }
    stamp(table);
    table.setAttribute('data-cardified', '1');
  });

  // rows appended later to an already-stamped table
  root.querySelectorAll('table[data-cardified="1"]').forEach(stamp);
}

/** Observe DOM changes and keep newly rendered tables stamped. */
export function watchTables(root = document.body) {
  let raf = null;
  const run = () => {
    raf = null;
    cardifyTables(root);
  };
  const schedule = () => {
    if (!raf) raf = requestAnimationFrame(run);
  };
  schedule();
  const mo = new MutationObserver(schedule);
  mo.observe(root, { childList: true, subtree: true });
  return () => {
    mo.disconnect();
    if (raf) cancelAnimationFrame(raf);
  };
}
