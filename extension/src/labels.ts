// labels.ts: pure names and labels, shared by the HTTP layer, the UI and the panel's HTML.
// No vscode import, so render.ts (and its Node tests) can use everything here.

import type { Finding } from './api';

/** Vulnerability names, copied exactly from patchai/models.py CWE_NAMES. */
export const CWE_NAMES: Record<string, string> = {
  'CWE-89': 'SQL injection',
  'CWE-78': 'Command injection',
  'CWE-22': 'Path traversal',
  'CWE-79': 'Cross-site scripting (XSS)',
  'CWE-798': 'Hard-coded secret',
  'CWE-327': 'Weak cryptography',
  'CWE-502': 'Unsafe deserialization',
};

/** What an attacker can do, per type (from the README's table). */
export const ATTACKER_CAN: Record<string, string> = {
  'CWE-89': 'read or change the database',
  'CWE-78': 'run commands on the server',
  'CWE-22': "read files they shouldn't (../../secrets)",
  'CWE-79': "run scripts in other users' browsers",
  'CWE-798': 'steal passwords written in the code',
  'CWE-327': 'break or predict hashes and tokens',
  'CWE-502': 'run code by uploading crafted data',
};

/** Model labels, kept in step with patchai/metrics.py MODEL_INFO. */
export const MODEL_LABELS: Record<string, string> = {
  'qwen2.5-coder:3b': 'Qwen2.5-Coder 3B (base)',
  'patchai-3b-v1': 'PatchAI-3B v1 (ours)',
  'patchai-3b': 'PatchAI-3B v2 (ours)',
  'patchai-3b-dpo': 'PatchAI-3B v2 + DPO (ours)',
  'qwen2.5-coder:7b': 'Qwen2.5-Coder 7B (base)',
};

export function modelLabel(model: string): string {
  return MODEL_LABELS[model] ?? model;
}

/** "SQL injection" for the seven known types, otherwise the CWE id or the scanner rule id. */
export function vulnerabilityName(finding: Finding): string {
  return (finding.cwe && CWE_NAMES[finding.cwe]) || finding.cwe || finding.rule_id;
}

/** Short label such as "CWE-89 SQL injection" (or just "CWE-123" / "B105" when the name is unknown). */
export function findingLabel(finding: Finding): string {
  const id = finding.cwe ?? finding.rule_id;
  const name = finding.cwe ? CWE_NAMES[finding.cwe] : undefined;
  return name ? `${id} ${name}` : id;
}

/** The key the findings store and the server both use to tell findings apart. */
export function findingKey(finding: Finding): string {
  return `${finding.file_path}|${finding.start_line}|${finding.cwe ?? finding.rule_id}`;
}
