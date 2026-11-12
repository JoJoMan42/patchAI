// Tests for the review panel's HTML (out/render.js). Run with: npm test
// render.ts has no vscode import, so plain Node can load it.

const test = require('node:test');
const assert = require('node:assert');
const { renderResult, renderWorking, renderChecks, renderDiff, esc, STEP_NAMES } = require('../out/render.js');

const finding = {
  id: 'f1', scanner: 'bandit', rule_id: 'B608', cwe: 'CWE-89', severity: 'high',
  file_path: 'shop/db.py', start_line: 12, end_line: 12, message: 'SQL built from a string', code: '',
};

function result(overrides = {}) {
  return {
    finding,
    model: 'patchai-3b',
    verdict: 'fixed',
    seconds: 6.2,
    diff: '--- a/shop/db.py\n+++ b/shop/db.py\n@@ -1,2 +1,2 @@\n-bad\n+good\n same\n',
    patched_file_text: 'good\nsame\n',
    retrieved: [],
    error: null,
    attempts: [{
      number: 1, seconds: 6, diff: '', raw_output: '', tokens_in: 100, tokens_out: 50,
      proposal: { status: 'fixed', fixed_code: 'good', imports_to_add: [], explanation: 'Use parameters.', confidence: 0.9 },
      checks: [
        { name: 'format', passed: true, details: '', skipped: false },
        { name: 'security_test', passed: true, details: 'no attack test', skipped: true },
      ],
    }],
    ...overrides,
  };
}

function acceptDisabled(html) {
  return /<button data-action="accept" disabled>/.test(html);
}

test('text from the model is escaped', () => {
  const r = result();
  r.attempts[0].proposal.explanation = '<script>alert(1)</script>';
  const html = renderResult(r, 'n0nce');
  assert.ok(html.includes('&lt;script&gt;alert(1)&lt;/script&gt;'));
  assert.ok(!html.includes('<script>alert(1)</script>'));
  assert.strictEqual(esc(`<a href="x">'&`), '&lt;a href=&quot;x&quot;&gt;&#39;&amp;');
});

test('a skipped check is rendered as skipped, not as passed', () => {
  const html = renderChecks([{ name: 'security_test', passed: true, details: '', skipped: true }]);
  assert.ok(html.includes('class="skip"'));
  assert.ok(html.includes('skipped'));
  assert.ok(!html.includes('✔'));
});

test('Accept is enabled only for a verified fix with a patched file', () => {
  assert.ok(!acceptDisabled(renderResult(result(), 'n')));
  for (const verdict of ['failed', 'cannot_fix', 'false_positive']) {
    assert.ok(acceptDisabled(renderResult(result({ verdict }), 'n')), verdict);
  }
  assert.ok(acceptDisabled(renderResult(result({ patched_file_text: null }), 'n')));
});

test('diff lines get the right class', () => {
  const html = renderDiff('--- a/f\n+++ b/f\n@@ -1 +1 @@\n-old\n+new\n ctx\n');
  assert.ok(html.includes('<span class="line file">--- a/f</span>'));
  assert.ok(html.includes('<span class="line hunk">@@ -1 +1 @@</span>'));
  assert.ok(html.includes('<span class="line del">-old</span>'));
  assert.ok(html.includes('<span class="line add">+new</span>'));
  assert.ok(html.includes('<span class="line context"> ctx</span>'));
});

test('the working page contains the five step names', () => {
  const html = renderWorking(finding, 'patchai-3b', 'n');
  for (const name of STEP_NAMES) {
    assert.ok(html.includes(name), name);
  }
  assert.strictEqual(STEP_NAMES.length, 5);
  assert.ok(html.includes('PatchAI-3B v2 (ours)'));
});

test('the content security policy uses the nonce', () => {
  const html = renderResult(result(), 'abc123');
  assert.ok(html.includes("script-src 'nonce-abc123'"));
  assert.ok(html.includes('<script nonce="abc123">'));
});
