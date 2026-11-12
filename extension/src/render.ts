// render.ts: pure functions that build the review panel's HTML. No vscode import, so
// Node's test runner can check them (extension/test/render.test.js). Everything that
// comes from the server or from source code goes through esc() before it enters HTML.

import type { Attempt, CheckResult, FixResult, Finding, RetrievedChunk } from './api';
import { modelLabel, vulnerabilityName } from './labels';

export const STEP_NAMES = ['Scanner', 'RAG', 'Our model', 'Checks', 'Human'];

/** Which of the five steps a pipeline stage belongs to (same mapping as the review app). */
export const STAGE_STEP: Record<string, number> = {
  context: 2, retrieve: 2, generate: 3, guard: 4, tests: 4,
  security_test: 4, rescan: 4, retry: 3, done: 5, error: 0,
};

const VERDICTS: Record<string, { label: string; css: string }> = {
  fixed: { label: 'Fixed and verified', css: 'fixed' },
  failed: { label: 'Not fixed', css: 'failed' },
  cannot_fix: { label: 'The model could not fix this safely', css: 'cannot-fix' },
  false_positive: { label: 'The model says this is a false alarm', css: 'false-positive' },
};

const CHECK_NAMES: Record<string, string> = {
  format: 'Readable answer',
  guard: 'Safety guard',
  tests: 'Project tests',
  security_test: 'Attack test',
  rescan: 'Re-scan',
};

const SOURCES: { source: RetrievedChunk['source']; label: string }[] = [
  { source: 'guide', label: 'Security guide' },
  { source: 'code', label: 'Project code' },
  { source: 'past_fix', label: 'Past fix' },
];

/** Escapes text before it goes into HTML. */
export function esc(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function page(nonce: string, title: string, body: string, script: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${esc(title)}</title>
  <style nonce="${nonce}">${STYLES}</style>
</head>
<body>
${body}
  <script nonce="${nonce}">${script}</script>
</body>
</html>`;
}

function stepsHtml(active: number, failed = false): string {
  const boxes = STEP_NAMES.map((name, index) => {
    const number = index + 1;
    const state = number < active ? 'done' : number === active ? (failed ? 'failed' : 'active') : 'waiting';
    return `<span class="step ${state}" data-step="${number}">${esc(name)}</span>`;
  });
  return `<div class="steps" id="steps">${boxes.join('<span class="arrow">→</span>')}</div>`;
}

// ---------- The working page (shown while the job runs) ----------

export function renderWorking(finding: Finding, model: string | null, nonce: string): string {
  const body = `
  ${headerHtml(finding)}
  <p class="muted">Model: <code>${esc(modelLabel(model ?? 'server default'))}</code></p>
  ${stepsHtml(1)}
  <h2>Progress</h2>
  <ul class="log" id="log"><li class="muted">Starting…</li></ul>`;
  return page(nonce, `Fixing ${vulnerabilityName(finding)}`, body, WORKING_SCRIPT);
}

function headerHtml(finding: Finding): string {
  const ids = [finding.cwe, `${finding.rule_id} (${finding.scanner})`].filter(Boolean).join(' · ');
  return `<header>
    <div class="title-row"><h1>${esc(vulnerabilityName(finding))}</h1></div>
    <div class="meta">
      <span><code>${esc(finding.file_path)}:${esc(finding.start_line)}</code></span>
      <span>${esc(ids)}</span>
      <span class="severity ${esc(finding.severity)}">${esc(finding.severity)} severity</span>
    </div>
    <p class="message">${esc(finding.message)}</p>
  </header>`;
}

// ---------- The result page ----------

export function renderResult(result: FixResult, nonce: string): string {
  const finalAttempt = result.attempts.at(-1);
  const earlierAttempts = result.attempts.slice(0, -1);
  const canAccept = result.verdict === 'fixed' && result.patched_file_text !== null;
  const canDiff = result.patched_file_text !== null;
  const verdict = VERDICTS[result.verdict] ?? { label: result.verdict, css: 'cannot-fix' };
  const tokensIn = result.attempts.reduce((n, a) => n + a.tokens_in, 0);
  const tokensOut = result.attempts.reduce((n, a) => n + a.tokens_out, 0);

  const body = `
  ${headerHtml(result.finding)}
  <div class="meta">
    <span class="badge ${verdict.css}">${esc(verdict.label)}</span>
    <span>model <code>${esc(modelLabel(result.model))}</code></span>
    <span>${esc(formatSeconds(result.seconds))}</span>
  </div>
  ${stepsHtml(result.verdict === 'fixed' ? 5 : 4, result.verdict !== 'fixed')}

  <div class="actions">
    <button data-action="accept"${canAccept ? '' : ' disabled'}>Accept</button>
    <button data-action="reject" class="secondary">Reject</button>
    <button data-action="openDiff" class="secondary"${canDiff ? '' : ' disabled'}>Open in diff editor</button>
    <button data-action="fixAgain" class="secondary">Fix again</button>
    <button data-action="tryModel" class="secondary">Try another model</button>
  </div>
  ${canAccept ? '' : `<p class="note">${esc(notVerifiedNote(result))}</p>`}
  ${result.error ? `<p class="note">${esc(result.error)}</p>` : ''}

  <h2>Explanation</h2>
  ${renderExplanation(finalAttempt)}

  <h2>Changes</h2>
  ${renderDiff(result.diff)}

  <h2>Checks${finalAttempt ? ` <span class="muted">(attempt ${esc(finalAttempt.number)} of ${esc(result.attempts.length)})</span>` : ''}</h2>
  ${renderChecks(finalAttempt?.checks ?? [])}
  ${renderEarlierAttempts(earlierAttempts)}

  <h2>What the AI read</h2>
  ${renderRetrieved(result.retrieved)}

  <p class="muted footer">${esc(result.attempts.length)} attempt(s) · ${esc(tokensIn)} tokens in · ${esc(tokensOut)} tokens out</p>`;
  return page(nonce, vulnerabilityName(result.finding), body, RESULT_SCRIPT);
}

function notVerifiedNote(result: FixResult): string {
  switch (result.verdict) {
    case 'failed':
      return 'Not fixed: a check failed on the final attempt, so nothing can be applied.';
    case 'cannot_fix':
      return 'The model could not fix this safely. Nothing can be applied.';
    case 'false_positive':
      return 'The model says this is a false alarm, so there is no fix to apply.';
    default:
      return 'This fix was not verified (the server returned no patched file), so it cannot be applied.';
  }
}

function renderExplanation(attempt: Attempt | undefined): string {
  const proposal = attempt?.proposal;
  if (!proposal) {
    const raw = attempt?.raw_output?.trim();
    return `<p class="muted">The model gave no usable answer.</p>${raw ? `<pre class="chunk-text">${esc(raw.slice(0, 2000))}</pre>` : ''}`;
  }
  const percent = Math.round(Math.min(1, Math.max(0, proposal.confidence ?? 0)) * 100);
  const imports = proposal.imports_to_add ?? [];
  return `<p class="explanation">${proposal.explanation ? esc(proposal.explanation) : '<span class="muted">No explanation given.</span>'}</p>
    <div class="confidence">
      <span>Confidence</span>
      <div class="bar"><div class="fill" data-percent="${percent}"></div></div>
      <span>${percent}%</span>
    </div>
    ${imports.length ? `<p class="muted">Adds ${imports.map(line => `<code>${esc(line)}</code>`).join(', ')}</p>` : ''}`;
}

/** Colours each line of a unified diff. Lines before the first "@@" are the file header. */
export function renderDiff(diff: string): string {
  if (!diff.trim()) {
    return '<p class="muted">No changes were proposed.</p>';
  }
  let inHeader = true;
  const lines = diff.replace(/\r?\n$/, '').split(/\r?\n/).map(line => {
    let kind = 'context';
    if (line.startsWith('@@')) {
      inHeader = false;
      kind = 'hunk';
    } else if (inHeader) {
      kind = 'file';
    } else if (line.startsWith('+')) {
      kind = 'add';
    } else if (line.startsWith('-')) {
      kind = 'del';
    }
    return `<span class="line ${kind}">${esc(line) || ' '}</span>`;
  });
  return `<pre class="diff"><code>${lines.join('')}</code></pre>`;
}

export function renderChecks(checks: CheckResult[]): string {
  if (checks.length === 0) {
    return '<p class="muted">No checks were run.</p>';
  }
  const items = checks.map(check => {
    const state = check.skipped ? 'skip' : check.passed ? 'pass' : 'fail';
    const icon = check.skipped ? '–' : check.passed ? '✔' : '✘';
    return `
    <li class="${state}">
      <span class="icon">${icon}</span>
      <div class="check-body">
        <strong>${esc(CHECK_NAMES[check.name] ?? check.name)}</strong>${check.skipped ? ' <span class="muted">skipped</span>' : ''}
        ${check.details ? `<pre class="details">${esc(check.details)}</pre>` : ''}
      </div>
    </li>`;
  });
  return `<ul class="checks">${items.join('')}</ul>`;
}

/** Earlier tries are collapsed, each with what the model was told next. */
function renderEarlierAttempts(attempts: Attempt[]): string {
  if (attempts.length === 0) {
    return '';
  }
  const blocks = attempts.map(attempt => {
    const failed = attempt.checks.filter(check => !check.passed && !check.skipped);
    const toldNext = failed.length
      ? `<h4>What the model was told next</h4><pre class="details">${esc(failed.map(c => `${CHECK_NAMES[c.name] ?? c.name}: ${c.details}`).join('\n').slice(0, 1500))}</pre>`
      : '';
    return `
    <details>
      <summary><span>${esc(attemptSummary(attempt))}</span></summary>
      <div class="details-body">
        ${attempt.proposal?.explanation ? `<p class="explanation">${esc(attempt.proposal.explanation)}</p>` : ''}
        ${renderChecks(attempt.checks)}
        ${renderDiff(attempt.diff)}
        ${toldNext}
      </div>
    </details>`;
  });
  return `<h3>Earlier attempts</h3>${blocks.join('')}`;
}

function attemptSummary(attempt: Attempt): string {
  const time = formatSeconds(attempt.seconds);
  const failed = attempt.checks.filter(check => !check.passed && !check.skipped).map(check => CHECK_NAMES[check.name] ?? check.name);
  if (failed.length > 0) {
    return `Attempt ${attempt.number} failed: ${failed.join(', ')} (${time})`;
  }
  if (!attempt.proposal) {
    return `Attempt ${attempt.number}: no usable answer (${time})`;
  }
  if (attempt.proposal.status !== 'fixed') {
    return `Attempt ${attempt.number}: model answered "${attempt.proposal.status.replace('_', ' ')}" (${time})`;
  }
  return `Attempt ${attempt.number} passed (${time})`;
}

/** Retrieved chunks grouped by source, best score first. */
function renderRetrieved(chunks: RetrievedChunk[]): string {
  if (chunks.length === 0) {
    return '<p class="muted">No context was retrieved.</p>';
  }
  return SOURCES.map(({ source, label }) => {
    const group = chunks.filter(chunk => chunk.source === source).sort((a, b) => b.score - a.score);
    if (group.length === 0) {
      return '';
    }
    const blocks = group.map(chunk => `
      <details>
        <summary>
          <span>${esc(chunk.title || chunk.file_path || 'Untitled')}</span>
          ${chunk.file_path && chunk.title ? `<code class="muted">${esc(chunk.file_path)}</code>` : ''}
          <span class="score">score ${esc((chunk.score ?? 0).toFixed(2))}</span>
        </summary>
        <div class="details-body"><pre class="chunk-text">${esc(chunk.text)}</pre></div>
      </details>`);
    return `<h3>${label} <span class="count">${group.length}</span></h3>${blocks.join('')}`;
  }).join('');
}

function formatSeconds(seconds: number): string {
  if (!Number.isFinite(seconds)) {
    return '';
  }
  if (seconds < 60) {
    return `${seconds.toFixed(1)} s`;
  }
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

// ---------- Webview scripts ----------

// The working page: receives {type:'events', events:[{stage,message}]} and updates the
// step strip and the log. The step mapping mirrors STAGE_STEP above.
const WORKING_SCRIPT = `
  const stageStep = ${JSON.stringify(STAGE_STEP)};
  const log = document.getElementById('log');
  const steps = Array.from(document.querySelectorAll('.step'));
  let shown = 0;
  let active = 1;

  function setActive(step, failed) {
    if (step > 0) { active = step; }
    steps.forEach(el => {
      const n = Number(el.dataset.step);
      el.className = 'step ' + (n < active ? 'done' : n === active ? (failed ? 'failed' : 'active') : 'waiting');
    });
  }

  window.addEventListener('message', event => {
    const data = event.data;
    if (!data || data.type !== 'events') { return; }
    for (const e of data.events.slice(shown)) {
      const li = document.createElement('li');
      const b = document.createElement('strong');
      b.textContent = e.stage;
      li.appendChild(b);
      li.appendChild(document.createTextNode(' · ' + e.message));
      if (shown === 0) { log.textContent = ''; }
      log.appendChild(li);
      shown += 1;
      setActive(stageStep[e.stage] ?? 4, e.stage === 'error');
    }
    window.scrollTo(0, document.body.scrollHeight);
  });
`;

// The result page: buttons send a message to the extension; Accept/Reject are locked
// until the extension answers, so a decision cannot be sent twice.
const RESULT_SCRIPT = `
  const vscode = acquireVsCodeApi();
  const buttons = Array.from(document.querySelectorAll('button[data-action]'));
  const usable = buttons.filter(button => !button.disabled);

  for (const button of buttons) {
    button.addEventListener('click', () => {
      if (button.dataset.action !== 'openDiff') {
        usable.forEach(b => { b.disabled = true; });
      }
      vscode.postMessage({ action: button.dataset.action });
    });
  }

  window.addEventListener('message', event => {
    if (event.data && event.data.type === 'enableButtons') {
      usable.forEach(b => { b.disabled = false; });
    }
  });

  // Inline style attributes are blocked by the CSP, so the confidence bar width is set here.
  document.querySelectorAll('[data-percent]').forEach(el => { el.style.width = el.dataset.percent + '%'; });
`;

// Only VS Code theme variables are used for colours, so the panel matches light and dark themes.
const STYLES = `
  body {
    margin: 0; padding: 0 20px 40px; line-height: 1.5;
    font-family: var(--vscode-font-family); font-size: var(--vscode-font-size);
    color: var(--vscode-foreground); background: var(--vscode-editor-background);
  }
  code, pre { font-family: var(--vscode-editor-font-family); font-size: var(--vscode-editor-font-size); }
  .muted { color: var(--vscode-descriptionForeground); }
  .footer { margin-top: 24px; }

  header { padding-top: 20px; }
  .title-row { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
  h1 { margin: 0; font-size: 1.7em; font-weight: 600; }
  h2 {
    margin: 28px 0 10px; padding-bottom: 4px; font-size: 1.15em; font-weight: 600;
    border-bottom: 1px solid var(--vscode-panel-border, rgba(128, 128, 128, 0.35));
  }
  h3 {
    margin: 18px 0 6px; font-size: 0.85em; font-weight: 600; letter-spacing: 0.05em;
    text-transform: uppercase; color: var(--vscode-descriptionForeground);
  }
  h4 { margin: 12px 0 4px; font-size: 0.9em; }
  .meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 18px; margin-top: 8px; color: var(--vscode-descriptionForeground); }
  .message { margin: 10px 0 0; }

  .steps { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin: 16px 0 4px; }
  .step { padding: 3px 10px; border-radius: 999px; border: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.4)); }
  .step.done { color: var(--vscode-testing-iconPassed, #388a34); border-color: currentColor; }
  .step.active { color: var(--vscode-button-foreground); background: var(--vscode-button-background); border-color: transparent; font-weight: 600; }
  .step.failed { color: var(--vscode-button-foreground); background: var(--vscode-testing-iconFailed, #e51400); border-color: transparent; font-weight: 600; }
  .step.waiting { color: var(--vscode-descriptionForeground); }
  .arrow { color: var(--vscode-descriptionForeground); }

  ul.log { list-style: none; margin: 0; padding: 8px 12px; border-radius: 4px;
    border: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.35));
    background: var(--vscode-textCodeBlock-background); }
  ul.log li { padding: 2px 0; }

  .badge {
    padding: 2px 12px; border-radius: 999px; border: 1px solid currentColor;
    font-weight: 600; font-size: 0.95em; white-space: nowrap;
    background: color-mix(in srgb, currentColor 14%, transparent);
  }
  .badge.fixed { color: var(--vscode-testing-iconPassed, #388a34); }
  .badge.failed { color: var(--vscode-testing-iconFailed, #e51400); }
  .badge.cannot-fix { color: var(--vscode-descriptionForeground); }
  .badge.false-positive { color: var(--vscode-charts-blue, #3794ff); }

  .severity { font-weight: 600; }
  .severity.high { color: var(--vscode-editorError-foreground); }
  .severity.medium { color: var(--vscode-editorWarning-foreground); }
  .severity.low { color: var(--vscode-editorInfo-foreground); }

  .actions {
    position: sticky; top: 0; z-index: 1; display: flex; flex-wrap: wrap; gap: 8px;
    margin-top: 16px; padding: 12px 0; background: var(--vscode-editor-background);
    border-bottom: 1px solid var(--vscode-panel-border, rgba(128, 128, 128, 0.35));
  }
  button {
    padding: 6px 16px; border-radius: 2px; cursor: pointer;
    font-family: inherit; font-size: inherit;
    color: var(--vscode-button-foreground); background: var(--vscode-button-background);
    border: 1px solid var(--vscode-button-border, transparent);
  }
  button:hover:not(:disabled) { background: var(--vscode-button-hoverBackground); }
  button.secondary { color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground); }
  button.secondary:hover:not(:disabled) { background: var(--vscode-button-secondaryHoverBackground); }
  button:disabled { opacity: 0.45; cursor: not-allowed; }
  button:focus-visible { outline: 1px solid var(--vscode-focusBorder); outline-offset: 2px; }
  .note {
    margin: 12px 0 0; padding: 8px 12px;
    border-left: 3px solid var(--vscode-editorWarning-foreground);
    background: var(--vscode-textBlockQuote-background);
  }

  .explanation { white-space: pre-wrap; margin: 0 0 10px; }
  .confidence { display: flex; align-items: center; gap: 10px; }
  .bar {
    width: 180px; height: 6px; border-radius: 3px; overflow: hidden;
    background: color-mix(in srgb, var(--vscode-foreground) 15%, transparent);
  }
  .fill { width: 0; height: 100%; background: var(--vscode-progressBar-background); }

  pre.diff {
    margin: 0; padding: 6px 0; overflow-x: auto; border-radius: 4px;
    background: var(--vscode-textCodeBlock-background);
    border: 1px solid var(--vscode-panel-border, rgba(128, 128, 128, 0.35));
  }
  pre.diff code { display: block; width: max-content; min-width: 100%; }
  .line { display: block; padding: 0 12px; white-space: pre; }
  .line.add {
    background: var(--vscode-diffEditor-insertedLineBackground, var(--vscode-diffEditor-insertedTextBackground, rgba(155, 185, 85, 0.2)));
    box-shadow: inset 3px 0 var(--vscode-gitDecoration-addedResourceForeground, #81b88b);
  }
  .line.del {
    background: var(--vscode-diffEditor-removedLineBackground, var(--vscode-diffEditor-removedTextBackground, rgba(255, 0, 0, 0.2)));
    box-shadow: inset 3px 0 var(--vscode-gitDecoration-deletedResourceForeground, #c74e39);
  }
  .line.hunk { color: var(--vscode-textLink-foreground); }
  .line.file { color: var(--vscode-descriptionForeground); font-weight: 600; }

  ul.checks { list-style: none; margin: 0; padding: 0; }
  ul.checks li {
    display: flex; gap: 10px; padding: 7px 0;
    border-bottom: 1px solid var(--vscode-panel-border, rgba(128, 128, 128, 0.2));
  }
  ul.checks li:last-child { border-bottom: none; }
  .icon { width: 1.2em; font-weight: 700; }
  li.pass .icon { color: var(--vscode-testing-iconPassed, #388a34); }
  li.fail .icon { color: var(--vscode-testing-iconFailed, #e51400); }
  li.skip .icon { color: var(--vscode-descriptionForeground); }
  .check-body { flex: 1; min-width: 0; }
  pre.details {
    margin: 4px 0 0; max-height: 14em; overflow: auto; white-space: pre-wrap; word-break: break-word;
    color: var(--vscode-descriptionForeground);
  }

  details {
    margin: 6px 0; border-radius: 4px;
    border: 1px solid var(--vscode-panel-border, rgba(128, 128, 128, 0.35));
  }
  summary {
    display: flex; align-items: center; gap: 10px; padding: 6px 10px;
    list-style: none; cursor: pointer; border-radius: 4px;
  }
  summary::-webkit-details-marker { display: none; }
  summary::before { content: '▸'; color: var(--vscode-descriptionForeground); transition: transform 0.15s; }
  details[open] > summary::before { transform: rotate(90deg); }
  summary:hover { background: var(--vscode-list-hoverBackground); }
  .details-body { padding: 4px 12px 12px; }
  pre.chunk-text {
    margin: 0; max-height: 22em; overflow: auto; padding: 8px 10px; border-radius: 3px;
    white-space: pre-wrap; word-break: break-word; background: var(--vscode-textCodeBlock-background);
  }
  .score, .count {
    padding: 0 8px; border-radius: 999px; font-size: 0.85em; white-space: nowrap;
    color: var(--vscode-badge-foreground); background: var(--vscode-badge-background);
  }
  .score { margin-left: auto; }
`;
