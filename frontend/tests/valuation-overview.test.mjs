import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
function loadModule(path, imports = {}) {
  const source = fs.readFileSync(new URL(path, import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: {
    jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const exports = {};
  new Function('require', 'exports', compiled)(id => imports[id] ?? require(id), exports);
  return exports;
}
const format = loadModule('../src/format.ts');
const Overview = loadModule('../src/components/ValuationOverview.tsx', { '../format': format }).default;
const baseline = {
  asset_value: 500_000_000, overhead_present_value: 100_000_000, net_cash: 200_000_000,
  equity_value: 600_000_000, value_per_share: 60, current_price: 75,
  price_to_sotp: 1.25, shares_outstanding: 10_000_000, price_as_of: '2026-10-02',
  price_source: 'twelve_data', discount_rate: 0.1, continuing_value: { value: 0 },
};
const render = changes => renderToStaticMarkup(createElement(Overview, { result: { ...baseline, ...changes }, busy: false }));

test('separates observed price from modeled value and preserves the price multiple', () => {
  const html = render({});
  for (const expected of ['$60.00', '$75.00', '1.25×', '2026-10-02', 'Price is above']) assert.ok(html.includes(expected));
});

test('missing company valuation is unavailable rather than a zero-dollar estimate', () => {
  const html = render({ asset_value: null, equity_value: null, value_per_share: null, price_to_sotp: null });
  assert.ok(html.includes('Insufficient drug inputs'));
  assert.ok(html.includes('N/A'));
  assert.ok(!html.includes('$0.00'));
  assert.ok(!html.includes('Price is above'));
});

test('net debt is shown as a deduction and analog-based pipeline value is labeled', () => {
  const html = render({ net_cash: -50_000_000, continuing_value: { value: 25_000_000, note: 'Industry analog estimate' } });
  for (const expected of ['Net debt', '−$50.0M', '−$100.0M', '+$25.0M', 'Based on an industry analog', 'Industry analog estimate']) assert.ok(html.includes(expected));
});

test('missing shares and sample prices remain explicit', () => {
  const html = render({ shares_outstanding: null, value_per_share: null, price_to_sotp: null, price_source: 'mock' });
  assert.ok(html.includes('Shares outstanding are needed'));
  assert.ok(html.includes('Sample data'));
  assert.ok(!html.includes('Divided by'));
});
