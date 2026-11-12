// api.ts: talks to the local PatchAI server (patchai/server.py).
// It holds the TypeScript types of the JSON the server sends, the CWE names, and one small
// fetch wrapper per endpoint. No other file makes HTTP requests.

import * as vscode from 'vscode';

// ---------- Data types (they mirror the server's JSON; see patchai/models.py) ----------

export type Severity = 'low' | 'medium' | 'high';
export type Verdict = 'fixed' | 'failed' | 'cannot_fix' | 'false_positive';
export type Decision = 'approved' | 'rejected';

/** A vulnerability reported by a scanner. */
export interface Finding {
  id: string;
  scanner: string;
  rule_id: string;
  cwe: string | null;
  severity: Severity;
  file_path: string; // relative to the project folder, forward slashes
  start_line: number; // 1-based
  end_line: number;
  message: string;
  code: string; // the flagged line(s), for display
}

/** One piece of information RAG found and gave to the model. */
export interface RetrievedChunk {
  source: 'guide' | 'code' | 'past_fix';
  title: string;
  text: string;
  file_path: string | null;
  score: number;
}

/** What the model answered in one attempt. */
export interface FixProposal {
  status: 'fixed' | 'cannot_fix' | 'false_positive';
  fixed_code: string;
  imports_to_add: string[];
  explanation: string;
  confidence: number; // 0 to 1
}

/** The result of one check (guard, tests, re-scan, ...). */
export interface CheckResult {
  name: 'format' | 'guard' | 'tests' | 'security_test' | 'rescan';
  passed: boolean;
  details: string;
  skipped: boolean; // true when the check could not run (e.g. no attack test exists)
}

/** One try of the fix loop. The proposal is null when the model's answer could not be parsed. */
export interface Attempt {
  number: number;
  seconds: number;
  diff: string;
  proposal: FixProposal | null;
  raw_output: string;
  checks: CheckResult[];
  tokens_in: number;
  tokens_out: number;
}

/** Everything the server knows about fixing one finding. */
export interface FixResult {
  finding: Finding;
  model: string;
  verdict: Verdict;
  seconds: number;
  diff: string; // unified diff of the final attempt
  patched_file_text: string | null; // full new file, or null when there is no usable fix
  retrieved: RetrievedChunk[];
  attempts: Attempt[];
  error: string | null; // set when the pipeline itself failed
}

export interface Health {
  ok: boolean;
  models: string[];
  default_model: string;
  version: string;
  root: string;
  ollama: boolean;
  fine_tuned: boolean;
  semgrep: boolean;
  problem: string | null;
}

/** One progress event of a running fix job. */
export interface FixEvent {
  stage: string;
  message: string;
}

export interface FixStatus {
  done: boolean;
  events: FixEvent[];
  result: FixResult | null;
  error: string | null;
}

// ---------- Names and labels (pure, shared with render.ts) ----------

export { ATTACKER_CAN, CWE_NAMES, MODEL_LABELS, findingKey, findingLabel, modelLabel, vulnerabilityName } from './labels';

// ---------- Errors ----------

/** The server is not running (or not reachable at patchai.serverUrl). */
export class ServerUnreachableError extends Error {}

/** The server answered with an HTTP error; the message is its "detail" text. */
export class ServerError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

// ---------- Requests ----------

const DEFAULT_URL = 'http://127.0.0.1:8765';
const SECOND = 1000;
const MINUTE = 60 * SECOND;

export function serverUrl(): string {
  const url = vscode.workspace.getConfiguration('patchai').get<string>('serverUrl', DEFAULT_URL).trim();
  return (url || DEFAULT_URL).replace(/\/+$/, '');
}

/** Sends one request and returns the parsed JSON, turning every failure into a readable error. */
async function request<T>(method: 'GET' | 'POST', path: string, body: unknown, timeoutMs: number): Promise<T> {
  const base = serverUrl();
  let response: Response;
  let text: string;
  try {
    response = await fetch(base + path, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    });
    text = await response.text();
  } catch (error) {
    if (isTimeout(error)) {
      throw new Error(`The PatchAI server did not answer within ${Math.round(timeoutMs / SECOND)} seconds.`);
    }
    throw new ServerUnreachableError(`Cannot reach the PatchAI server at ${base}. Is it running?`);
  }

  let data: unknown;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    data = undefined; // not JSON; handled below
  }

  if (!response.ok) {
    throw new ServerError(`PatchAI server error (${response.status}): ${errorDetail(data, text, response.statusText)}`, response.status);
  }
  if (data === undefined) {
    throw new Error(`The PatchAI server sent an invalid response to ${path}.`);
  }
  return data as T;
}

/** Our own timeout, or Node's built-in fetch timeouts. */
function isTimeout(error: unknown): boolean {
  const err = error as { name?: string; cause?: { code?: string } } | undefined;
  return err?.name === 'TimeoutError' || err?.cause?.code === 'UND_ERR_HEADERS_TIMEOUT' || err?.cause?.code === 'UND_ERR_BODY_TIMEOUT';
}

/** FastAPI sends {"detail": "text"}, or {"detail": [{"msg": ...}]} for invalid requests. */
function errorDetail(data: unknown, text: string, statusText: string): string {
  const detail = (data as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map(item => (item as { msg?: string }).msg ?? JSON.stringify(item)).join('; ');
  }
  return text.trim() || statusText || 'unknown error';
}

// ---------- Endpoints ----------

export function getHealth(): Promise<Health> {
  return request<Health>('GET', '/health', undefined, 10 * SECOND);
}

export async function scan(projectDir: string): Promise<Finding[]> {
  const data = await request<{ findings: Finding[] }>('POST', '/scan', { project_dir: projectDir }, 3 * MINUTE);
  return data.findings ?? [];
}

/** Starts a fix as a background job on the server; poll it with fixStatus. */
export async function startFix(projectDir: string, finding: Finding, model: string | null): Promise<string> {
  const data = await request<{ job_id: string }>(
    'POST', '/fix/start', { project_dir: projectDir, finding, model }, 30 * SECOND,
  );
  return data.job_id;
}

/** The job's progress events so far and, once done, its result or error. */
export async function fixStatus(jobId: string): Promise<FixStatus> {
  const status = await request<FixStatus>('GET', `/fix/status/${jobId}`, undefined, 30 * SECOND);
  return { ...status, result: status.result ? normalize(status.result) : null };
}

/** The safe demo copy of the vulnerable shop. */
export async function demoProject(reset: boolean): Promise<string> {
  const data = await request<{ project_dir: string }>('POST', '/demo', { reset }, 30 * SECOND);
  return data.project_dir;
}

/**
 * The old blocking fix endpoint, kept only for compatibility.
 * @deprecated Use startFix + fixStatus, which survive fixes longer than Node's 5-minute fetch limit.
 */
export async function fix(projectDir: string, finding: Finding, model: string | null): Promise<FixResult> {
  const result = await request<FixResult>('POST', '/fix', { project_dir: projectDir, finding, model }, 5 * MINUTE);
  return normalize(result);
}

/** Fills in missing fields so the panel never has to guard against them. */
function normalize(result: FixResult): FixResult {
  return {
    ...result,
    diff: result.diff ?? '',
    error: result.error ?? null,
    retrieved: result.retrieved ?? [],
    attempts: (result.attempts ?? []).map(attempt => ({
      ...attempt,
      diff: attempt.diff ?? '',
      raw_output: attempt.raw_output ?? '',
      proposal: attempt.proposal ?? null,
      checks: (attempt.checks ?? []).map(check => ({ ...check, skipped: check.skipped ?? false })),
      tokens_in: attempt.tokens_in ?? 0,
      tokens_out: attempt.tokens_out ?? 0,
    })),
  };
}

/** Records the human's decision so the team can learn from approved and rejected fixes. */
export async function sendDecision(
  projectDir: string,
  findingId: string,
  decision: Decision,
  reason: string | null,
  model: string,
): Promise<void> {
  await request<{ ok: boolean }>(
    'POST',
    '/decision',
    { project_dir: projectDir, finding_id: findingId, decision, reason, model },
    30 * SECOND,
  );
}
