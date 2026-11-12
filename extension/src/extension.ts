// extension.ts: the entry point. It creates the pieces and registers the commands;
// everything else lives in its own file: api.ts (HTTP), server.ts (start/stop the server),
// findings.ts (diagnostics, side bar, status bar), fix.ts (the fix flow), panel.ts +
// render.ts (the review panel).

import * as vscode from 'vscode';
import * as api from './api';
import * as findings from './findings';
import * as fix from './fix';
import * as server from './server';

export function activate(context: vscode.ExtensionContext): void {
  server.setExtensionPath(context.extensionPath);
  server.init(context);
  findings.init(context);
  fix.init(context);

  context.subscriptions.push(
    vscode.commands.registerCommand('patchai.scan', () => findings.scanWorkspace(false)),
    vscode.commands.registerCommand('patchai.fix', (arg?: unknown) => fix.fixFinding(arg)),
    vscode.commands.registerCommand('patchai.selectModel', () => fix.selectModel()),
    vscode.commands.registerCommand('patchai.checkSetup', checkSetup),
    vscode.commands.registerCommand('patchai.openDemo', openDemoProject),
  );

  void findings.scanOnOpen();
}

export function deactivate(): void {
  server.stopServer();
}

/** Starts the server if needed, then shows a checklist built from /health. */
async function checkSetup(): Promise<void> {
  const health = await server.ensureServer(true);
  if (!health) {
    return;
  }
  const line = (ok: boolean, name: string, fixHint: string) =>
    `${ok ? '$(check)' : '$(error)'} ${name}${ok ? '' : ` — ${fixHint}`}`;
  const lines = [
    line(true, `Server ${health.version} at ${api.serverUrl()}`, ''),
    line(health.ollama, 'Ollama', 'install it from ollama.com and run `ollama serve`'),
    line(health.fine_tuned, `Fine-tuned model (${api.modelLabel(health.default_model)})`,
      health.problem ?? 'register it with training/export.py'),
    line(health.semgrep, 'Semgrep', 'pip install semgrep (path traversal and XSS need it)'),
  ];
  const ready = health.ollama && health.fine_tuned && health.semgrep;
  const items = lines.map(label => ({ label }));
  const picked = await vscode.window.showQuickPick(items, {
    title: ready ? 'PatchAI setup: everything is ready' : 'PatchAI setup: something is missing',
    placeHolder: ready ? 'Press Escape to close' : 'Fix the marked lines, then run Check Setup again',
  });
  void picked;
}

/** Resets the safe demo copy of the vulnerable shop and opens it in a new window. */
async function openDemoProject(): Promise<void> {
  const health = await server.ensureServer(true);
  if (!health) {
    return;
  }
  try {
    const folder = await api.demoProject(true);
    await vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(folder), { forceNewWindow: true });
  } catch (error) {
    void findings.showError(error);
  }
}
