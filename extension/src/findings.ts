// findings.ts: one store for the scan results, and every way they are shown: diagnostics
// (underlines + Problems panel), quick fixes, hovers, CodeLens, the PatchAI side bar,
// and the two status bar items. Scans are started here too.

import * as vscode from 'vscode';
import * as api from './api';
import { Finding } from './api';
import { findingKey } from './labels';
import * as server from './server';

let diagnostics: vscode.DiagnosticCollection;
let scanStatus: vscode.StatusBarItem;
let modelStatus: vscode.StatusBarItem;
let tree: FindingsTree;
let scanRunning = false;

/** Every finding of the last scan, keyed by file|line|cwe (the server's own duplicate key). */
const store = new Map<string, Finding>();

export function init(context: vscode.ExtensionContext): void {
  diagnostics = vscode.languages.createDiagnosticCollection('patchai');
  tree = new FindingsTree();

  scanStatus = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  scanStatus.command = 'patchai.scan';
  setScanStatus('$(shield) PatchAI', 'Scan the workspace for vulnerabilities');
  scanStatus.show();

  modelStatus = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 99);
  modelStatus.command = 'patchai.selectModel';
  modelStatus.text = '$(hubot) PatchAI model';
  modelStatus.tooltip = 'PatchAI model: click to change';
  modelStatus.show();
  void refreshModelStatus();

  context.subscriptions.push(
    diagnostics,
    scanStatus,
    modelStatus,
    vscode.window.registerTreeDataProvider('patchai.findings', tree),
    vscode.languages.registerCodeActionsProvider(
      { language: 'python' },
      { provideCodeActions: (_document, _range, ctx) => fixActions(ctx.diagnostics) },
      { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] },
    ),
    vscode.languages.registerHoverProvider({ language: 'python' }, { provideHover }),
    vscode.languages.registerCodeLensProvider({ language: 'python' }, { provideCodeLenses }),
    vscode.workspace.onDidSaveTextDocument(document => {
      const scanOnSave = vscode.workspace.getConfiguration('patchai').get<boolean>('scanOnSave', true);
      if (scanOnSave && document.languageId === 'python' && vscode.workspace.workspaceFolders) {
        void scanWorkspace(true);
      }
    }),
    vscode.workspace.onDidChangeConfiguration(event => {
      if (event.affectsConfiguration('patchai.model')) {
        void refreshModelStatus();
      }
    }),
  );
}

/** A start-up scan: only when the folder has Python files and PatchAI is found without asking. */
export async function scanOnOpen(): Promise<void> {
  const config = vscode.workspace.getConfiguration('patchai');
  if (!config.get<boolean>('scanOnOpen', true) || !vscode.workspace.workspaceFolders) {
    return;
  }
  const pythonFiles = await vscode.workspace.findFiles('**/*.py', '**/{.venv,venv,node_modules}/**', 1);
  if (pythonFiles.length === 0) {
    return;
  }
  if (config.get<boolean>('autoStartServer', true)) {
    const folder = await server.findPatchaiFolder(false);
    if (!folder) {
      setScanStatus('$(shield) PatchAI: server offline', 'Click to start the PatchAI server');
      scanStatus.command = 'patchai.startServer';
      return;
    }
    setScanStatus('$(sync~spin) PatchAI: starting…', 'Starting the PatchAI server');
    const health = await server.ensureServer(false);
    if (!health) {
      setScanStatus('$(shield) PatchAI: server offline', 'Click to start the PatchAI server');
      scanStatus.command = 'patchai.startServer';
      return;
    }
  }
  await scanWorkspace(true);
  void refreshModelStatus();
}

// ---------- The store ----------

export function allFindings(): Finding[] {
  return [...store.values()];
}

export function findingForDiagnostic(uri: vscode.Uri, diagnostic: vscode.Diagnostic): Finding | undefined {
  if (diagnostic.source !== 'PatchAI') {
    return undefined;
  }
  const folder = vscode.workspace.getWorkspaceFolder(uri) ?? vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    return undefined;
  }
  const relative = vscode.workspace.asRelativePath(uri, false).replace(/\\/g, '/');
  const line = diagnostic.range.start.line + 1;
  const cwe = typeof diagnostic.code === 'object' ? String(diagnostic.code.value) : String(diagnostic.code ?? '');
  return store.get(`${relative}|${line}|${cwe}`);
}

function findingsAt(uri: vscode.Uri, line: number): Finding[] {
  const relative = vscode.workspace.asRelativePath(uri, false).replace(/\\/g, '/');
  return [...store.values()].filter(f => f.file_path === relative && f.start_line - 1 <= line && line <= f.end_line - 1);
}

// ---------- Scanning ----------

/** POST /scan for the first workspace folder. Quiet scans never show popups (only the status bar). */
export async function scanWorkspace(quiet: boolean): Promise<void> {
  const folder = projectFolder(quiet);
  if (!folder || scanRunning) {
    return;
  }
  if (!quiet) {
    const health = await server.ensureServer(true);
    if (!health) {
      return;
    }
  }
  scanRunning = true;
  setScanStatus('$(sync~spin) PatchAI: scanning…', 'Scanning the workspace');
  try {
    const findings = quiet
      ? await api.scan(folder.uri.fsPath)
      : await vscode.window.withProgress(
          { location: vscode.ProgressLocation.Notification, title: 'PatchAI: scanning the workspace…' },
          () => api.scan(folder.uri.fsPath),
        );
    await showFindings(folder, findings);
    if (!quiet) {
      announceScan(findings.length);
    }
  } catch (error) {
    if (error instanceof api.ServerUnreachableError) {
      setScanStatus('$(shield) PatchAI: server offline', 'Click to start the PatchAI server');
      scanStatus.command = 'patchai.startServer';
    } else {
      setScanStatus('$(shield) PatchAI: scan failed', 'Click to try again');
    }
    if (!quiet) {
      void showError(error);
    }
  } finally {
    scanRunning = false;
  }
}

async function showFindings(folder: vscode.WorkspaceFolder, findings: Finding[]): Promise<void> {
  diagnostics.clear();
  store.clear();
  for (const finding of findings) {
    store.set(findingKey(finding), finding);
  }
  tree.refresh();

  const files = new Map<string, { uri: vscode.Uri; lines: string[]; items: vscode.Diagnostic[] }>();
  for (const finding of findings) {
    const uri = findingUri(folder, finding);
    let file = files.get(uri.toString());
    if (!file) {
      file = { uri, lines: await readLines(uri), items: [] };
      files.set(uri.toString(), file);
    }
    file.items.push(toDiagnostic(finding, file.lines));
  }
  for (const file of files.values()) {
    diagnostics.set(file.uri, file.items);
  }

  const count = (severity: api.Severity) => findings.filter(f => f.severity === severity).length;
  const total = findings.length;
  scanStatus.command = 'patchai.scan';
  setScanStatus(
    `$(shield) PatchAI: ${total === 0 ? 'no issues' : total === 1 ? '1 issue' : `${total} issues`}`,
    `${count('high')} high · ${count('medium')} medium · ${count('low')} low\nClick to scan again`,
  );
  scanStatus.backgroundColor = total > 0 ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined;
}

function toDiagnostic(finding: Finding, lines: string[]): vscode.Diagnostic {
  const severities: Record<api.Severity, vscode.DiagnosticSeverity> = {
    high: vscode.DiagnosticSeverity.Error,
    medium: vscode.DiagnosticSeverity.Warning,
    low: vscode.DiagnosticSeverity.Information,
  };
  const diagnostic = new vscode.Diagnostic(
    findingRange(finding, lines),
    `${api.findingLabel(finding)}: ${finding.message}`,
    severities[finding.severity] ?? vscode.DiagnosticSeverity.Warning,
  );
  diagnostic.source = 'PatchAI';
  const cweNumber = finding.cwe?.match(/^CWE-(\d+)$/)?.[1];
  diagnostic.code = finding.cwe && cweNumber
    ? { value: finding.cwe, target: vscode.Uri.parse(`https://cwe.mitre.org/data/definitions/${cweNumber}.html`) }
    : (finding.cwe ?? finding.rule_id);
  return diagnostic;
}

function findingRange(finding: Finding, lines: string[]): vscode.Range {
  const start = Math.max(finding.start_line - 1, 0);
  const end = Math.max(finding.end_line - 1, start);
  const firstLine = lines[start] ?? '';
  const startColumn = firstLine.length - firstLine.trimStart().length;
  return new vscode.Range(start, startColumn, end, (lines[end] ?? '').length);
}

async function readLines(uri: vscode.Uri): Promise<string[]> {
  try {
    const bytes = await vscode.workspace.fs.readFile(uri);
    return Buffer.from(bytes).toString('utf8').split(/\r?\n/);
  } catch {
    return [];
  }
}

function announceScan(total: number): void {
  if (total === 0) {
    void vscode.window.showInformationMessage('PatchAI found no vulnerabilities.');
    return;
  }
  const text = `PatchAI found ${total} ${total === 1 ? 'vulnerability' : 'vulnerabilities'}. Fix one from the PatchAI side bar, a quick fix, or the CodeLens above the line.`;
  void vscode.window.showInformationMessage(text, 'Show PatchAI').then(choice => {
    if (choice) {
      void vscode.commands.executeCommand('patchai.findings.focus');
    }
  });
}

// ---------- Quick fixes, hover, CodeLens ----------

function fixActions(contextDiagnostics: readonly vscode.Diagnostic[]): vscode.CodeAction[] {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    return [];
  }
  const ours = contextDiagnostics
    .map(diagnostic => findingForDiagnostic(editor.document.uri, diagnostic))
    .filter((finding): finding is Finding => finding !== undefined);
  return ours.map((finding, index) => {
    const title = ours.length > 1 ? `🛡️ Fix with PatchAI: ${api.findingLabel(finding)}` : '🛡️ Fix with PatchAI';
    const action = new vscode.CodeAction(title, vscode.CodeActionKind.QuickFix);
    action.isPreferred = index === 0;
    action.command = { command: 'patchai.fix', title, arguments: [finding] };
    return action;
  });
}

function provideHover(document: vscode.TextDocument, position: vscode.Position): vscode.Hover | undefined {
  const here = findingsAt(document.uri, position.line);
  if (here.length === 0) {
    return undefined;
  }
  const finding = here[0];
  const attack = finding.cwe ? api.ATTACKER_CAN[finding.cwe] : undefined;
  const text = new vscode.MarkdownString(
    `**${api.findingLabel(finding)}** · ${finding.severity} severity\n\n` +
    (attack ? `An attacker can **${attack}**.\n\n` : '') +
    `${finding.message}\n\n` +
    `[🛡️ Fix with PatchAI](command:patchai.fix?${encodeURIComponent(JSON.stringify([finding]))})`,
  );
  text.isTrusted = { enabledCommands: ['patchai.fix'] };
  return new vscode.Hover(text);
}

function provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
  const relative = vscode.workspace.asRelativePath(document.uri, false).replace(/\\/g, '/');
  return [...store.values()]
    .filter(finding => finding.file_path === relative)
    .map(finding => new vscode.CodeLens(
      new vscode.Range(finding.start_line - 1, 0, finding.start_line - 1, 0),
      {
        command: 'patchai.fix',
        title: `🛡️ Fix ${api.vulnerabilityName(finding)} with PatchAI`,
        arguments: [finding],
      },
    ));
}

// ---------- The side bar ----------

type TreeNode = { kind: 'file'; file: string } | { kind: 'finding'; finding: Finding };

class FindingsTree implements vscode.TreeDataProvider<TreeNode> {
  private emitter = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.emitter.event;

  refresh(): void {
    this.emitter.fire();
  }

  getChildren(node?: TreeNode): TreeNode[] {
    if (!node) {
      const files = [...new Set([...store.values()].map(f => f.file_path))].sort();
      return files.map(file => ({ kind: 'file', file }));
    }
    if (node.kind === 'file') {
      return [...store.values()]
        .filter(f => f.file_path === node.file)
        .sort((a, b) => a.start_line - b.start_line)
        .map(finding => ({ kind: 'finding', finding }));
    }
    return [];
  }

  getTreeItem(node: TreeNode): vscode.TreeItem {
    if (node.kind === 'file') {
      const item = new vscode.TreeItem(node.file, vscode.TreeItemCollapsibleState.Expanded);
      item.iconPath = vscode.ThemeIcon.File;
      item.resourceUri = vscode.Uri.file(node.file);
      return item;
    }
    const finding = node.finding;
    const item = new vscode.TreeItem(`${api.vulnerabilityName(finding)} · line ${finding.start_line}`);
    item.description = finding.severity;
    item.tooltip = finding.message;
    item.contextValue = 'patchaiFinding';
    item.iconPath = new vscode.ThemeIcon(
      finding.severity === 'high' ? 'error' : finding.severity === 'medium' ? 'warning' : 'info',
    );
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (folder) {
      item.command = {
        command: 'vscode.open',
        title: 'Open',
        arguments: [
          findingUri(folder, finding),
          { selection: new vscode.Range(finding.start_line - 1, 0, finding.start_line - 1, 0) },
        ],
      };
    }
    return item;
  }
}

// ---------- Status bar ----------

export function setFixing(active: boolean): void {
  if (active) {
    setScanStatus('$(sync~spin) PatchAI: fixing…', 'A fix is running');
  } else {
    setScanStatus('$(shield) PatchAI', 'Scan the workspace for vulnerabilities');
  }
}

export async function refreshModelStatus(): Promise<void> {
  const configured = vscode.workspace.getConfiguration('patchai').get<string>('model', '').trim();
  if (configured) {
    modelStatus.text = `$(hubot) ${api.modelLabel(configured)}`;
    modelStatus.tooltip = 'PatchAI model (from your settings): click to change';
    return;
  }
  try {
    const health = await api.getHealth();
    const warn = health.fine_tuned ? '' : '$(warning) ';
    modelStatus.text = `${warn}$(hubot) ${api.modelLabel(health.default_model)}`;
    modelStatus.tooltip = health.fine_tuned
      ? 'PatchAI model: click to change'
      : `${health.problem ?? 'The fine-tuned model is not installed; the base model is used.'}\nClick to change the model.`;
  } catch {
    modelStatus.text = '$(hubot) PatchAI model';
    modelStatus.tooltip = 'PatchAI model: click to change (server offline)';
  }
}

function setScanStatus(text: string, tooltip: string): void {
  scanStatus.text = text;
  scanStatus.tooltip = tooltip;
  scanStatus.backgroundColor = undefined;
}

// ---------- Helpers ----------

export function projectFolder(quiet = false): vscode.WorkspaceFolder | undefined {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder && !quiet) {
    void vscode.window.showWarningMessage('PatchAI: open your project folder first (File > Open Folder).');
  }
  return folder;
}

export function findingUri(folder: vscode.WorkspaceFolder, finding: Finding): vscode.Uri {
  return vscode.Uri.joinPath(folder.uri, finding.file_path);
}

export async function showError(error: unknown): Promise<void> {
  const message = error instanceof Error ? error.message : String(error);
  if (error instanceof api.ServerUnreachableError) {
    const choice = await vscode.window.showErrorMessage(message, 'Start Server');
    if (choice === 'Start Server') {
      await vscode.commands.executeCommand('patchai.startServer');
    }
  } else {
    void vscode.window.showErrorMessage(message);
  }
}
