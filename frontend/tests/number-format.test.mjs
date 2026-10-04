import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

function load(path, imports = {}) {
  const compiled = ts.transpileModule(fs.readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  new Function('require', 'exports', compiled)(id => imports[id], exports);
  return exports;
}
const format = load('../src/format.ts');
const { normalizeNumberInput, formatNumberInput, numberInputError } = load('../src/numberInput.ts', { './format': format });

test('financial totals and share counts use full grouped numbers, and prices retain cents', () => {
  assert.equal(format.formatNumber(1000), '1,000');
  assert.equal(format.formatUSD(10000), '$10,000');
  assert.equal(format.formatUSD(-1234567890), '-$1,234,567,890');
  assert.equal(format.formatUSD(10000000, 'shares'), '10,000,000 sh');
  assert.equal(format.formatPrice(1234.56), '$1,234.56');
  assert.equal(format.formatPrice(-1234.5), '-$1,234.50');
  for (const value of [null, undefined, NaN, Infinity]) {
    assert.equal(format.formatUSD(value), '—');
    assert.equal(format.formatPrice(value), '—');
  }
});

test('amount inputs accept grouped pasted numbers without rounding the stored value', () => {
  const raw = normalizeNumberInput(' 1,000,000.50 ');
  assert.equal(raw, '1000000.50');
  assert.equal(Number(raw), 1000000.5);
  assert.equal(formatNumberInput(raw), '1,000,000.50');
  assert.equal(formatNumberInput('10000.'), '10,000.');
  assert.equal(formatNumberInput('-1234.56789'), '-1,234.56789');
  assert.equal(normalizeNumberInput('1,00'), '1,00');
  assert.ok(numberInputError(normalizeNumberInput('1,00')));
});

test('compact cards use M/B/T while smaller amounts retain commas', () => {
  assert.equal(format.formatCompactUSD(1000), '$1,000');
  assert.equal(format.formatCompactUSD(10000), '$10,000');
  assert.equal(format.formatCompactUSD(1500000), '$1.5M');
  assert.equal(format.formatCompactUSD(-1500000000), '-$1.5B');
  assert.equal(format.formatCompactUSD(1250000000000), '$1.25T');
  assert.equal(format.formatCompactUSD(1000000000000000), '$1,000T');
  assert.equal(format.formatCompactUSD(10000000, 'shares'), '10M sh');
  assert.equal(format.formatCompactUSD(999999999), '$1B');
  assert.equal(format.formatCompactUSD(999999999999), '$1T');
  assert.equal(format.formatUSD(1500000000), '$1,500,000,000');
  assert.equal(format.formatFigure(1500000000, 'USD'), '$1.5B');
  assert.equal(format.formatFigure(.125, 'ratio'), '12.5%');
  assert.equal(format.formatFigure(12.5, 'quarters'), '12.5 qtrs');
  for (const value of [null, undefined, NaN, Infinity]) assert.equal(format.formatCompactUSD(value), '—');
});

test('text amount fields retain numeric bounds and cent increments', () => {
  const limits = { min: 1, max: 1000000000, step: .01 };
  for (const value of ['1', '10000.25', '999999999.99', '1000000000']) assert.equal(numberInputError(value, limits), '');
  for (const value of ['0', '-1', '1000000001', '1.001', 'NaN', 'Infinity', '1e3']) assert.ok(numberInputError(value, limits));
  assert.equal(numberInputError('1234.56789', { min: 0, step: 'any' }), '');
  assert.equal(numberInputError('', limits), '');
});
