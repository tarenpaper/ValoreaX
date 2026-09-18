import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

// Execute the real API client with an in-memory auth service and HTTP transport.
function clientHarness() {
  let session = { access_token: 'account-A', expires_at: Date.now() / 1000 + 3600 };
  const sent = [];
  const supabase = { auth: {
    getSession: async () => ({ data: { session }, error: null }),
    signOut: async () => { session = null; },
  } };
  const source = fs.readFileSync(new URL('../src/api/client.ts', import.meta.url), 'utf8')
    .replaceAll('import.meta.env', '{}');
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const exports = {};
  new Function('require', 'exports', 'fetch', compiled)(() => ({ supabase }), exports,
    async (_url, options) => {
      sent.push(options.headers.get('Authorization'));
      return { ok: true, text: async () => '{}' };
    });
  return { api: exports.api, sent, changeSession: value => { session = value; } };
}

test('requests follow account changes without reloading the page', async () => {
  const h = clientHarness();
  await h.api.meta();
  h.changeSession({ access_token: 'account-B', expires_at: Date.now() / 1000 + 3600 });
  await h.api.meta();
  assert.deepEqual(h.sent, ['Bearer account-A', 'Bearer account-B']);
});

test('sign-out prevents reuse of an unexpired access token', async () => {
  const h = clientHarness();
  await h.api.meta();
  h.changeSession(null);
  await assert.rejects(h.api.meta(), { code: 'unauthorized' });
  assert.equal(h.sent.length, 1);
});

test('requests use a refreshed token immediately', async () => {
  const h = clientHarness();
  await h.api.meta();
  h.changeSession({ access_token: 'refreshed-A', expires_at: Date.now() / 1000 + 3600 });
  await h.api.meta();
  assert.equal(h.sent[1], 'Bearer refreshed-A');
});
