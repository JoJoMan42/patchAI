// fix.ts: the fix flow. It starts a fix job on the server, shows live progress in the
// panel, and carries out Accept (with a stale-file check and Undo), Reject, the diff
// editor, Fix again and Try another model.

import * as path from 'path';
import * as vscode from 'vscode';
import * as api from './api';
import { Finding, FixResult } from './api';
import * as findings from './findings';
import { PanelAction, closeFixPanel, postEvents, showResultPanel, showWorkingPanel } from './panel';
import * as server from './server';

const PROPOSED_SCHEME = 'patchai-proposed';
const REJECT_REASONS = ['Wrong fix', 'Breaks behaviour', 'Too large', 'Not a real vulnerability'];
const POLL_MS = 500;

let fixRunning = false;

// Text of proposed files for the diff editor, keyed by the virtual document's query string.
const proposedTexts = new Map<string, string>();
let diffCounter = 0;

export function init(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.workspace.registerTextDocumentContentProvider(PROPOSED_SCHEME, {
      provideTextDocumentContent: uri => proposedTexts.get(uri.query) ?? '',
    }),
  );
}

/** Runs from the quick fix / CodeLens / side bar (with a Finding) or from the palette (cursor). */
export async function fixFinding(arg?: unknown, modelOverride?: string | null): Promise<void> {
  if (fixRunning) {
    void vscode.window.showInformationMessage('PatchAI is already fixing something. One fix at a time.');
    return;
  }
  const folder = findings.projectFolder();
  if (!folder) {
    return;
  }
  const finding = isFinding(arg) ? arg : await pickFindingAtCursor();
  if (!finding) {
    return;
  }
  const health = await server.ensureServer(true);
  if (!health) {
    return;
  }
  const model = modelOverride !== undefined ? modelOverride : configuredModel();

  // Remember the file as it was when the fix started, for the stale check and for Undo.
  const uri = findings.findingUri(folder, finding);
  let original: string;
  try {
    original = Buffer.from(await vscode.workspace.fs.readFile(uri)).toString('utf8');
  } catch {
    void vscode.window.showErrorMessage(`PatchAI cannot read ${finding.file_path}.`);
    return;
  }

  fixRunning = true;
  findings.setFixing(true);
  showWorkingPanel(finding, model);
  try {
    const result = await runJob(folder, finding, model);
    if (result) {
      showResultPanel(result, action => handlePanelAction(action, folder, result, original));
    }
  } catch (error) {
    closeFixPanel();
    void findings.showError(error);
  } finally {
    fixRunning = false;
    findings.setFixing(false);
  }
}

/** Starts the job and polls it, streaming events to the panel. Returns null when cancelled. */
async function runJob(
  folder: vscode.WorkspaceFolder,
  finding: Finding,
  model: string | null,
): Promise<FixResult | null> {
  const jobId = await api.startFix(folder.uri.fsPath, finding, model);

  return vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `PatchAI is fixing ${api.vulnerabilityName(finding)}…`,
      cancellable: true,
    },
    async (progress, token) => {
      const started = Date.now();
      for (;;) {
        if (token.isCancellationRequested) {
          closeFixPanel();
          void vscode.window.showInformationMessage(
            'Stopped watching the fix. The server finishes the job in the background.',
          );
          return null;
        }
        const status = await api.fixStatus(jobId);
        postEvents(status.events);
        const latest = status.events.at(-1);
        const seconds = Math.round((Date.now() - started) / 1000);
        progress.report({ message: `${latest?.message ?? 'working'} (${seconds} s)` });
        if (status.done) {
          if (status.error) {
            throw new Error(status.error);
          }
          return status.result;
        }
        await sleep(POLL_MS);
      }
    },
  );
}

function isFinding(value: unknown): value is Finding {
  return typeof value === 'object' && value !== null && 'rule_id' in value && 'file_path' in value;
}

async function pickFindingAtCursor(): Promise<Finding | undefined> {
  const editor = vscode.window.activeTextEditor;
  const line = editor?.selection.active.line ?? -1;
  const relative = editor
    ? vscode.workspace.asRelativePath(editor.document.uri, false).replace(/\\/g, '/')
    : '';
  const here = findings.allFindings().filter(
    f => f.file_path === relative && f.start_line - 1 <= line && line <= f.end_line - 1,
  );
  if (here.length === 0) {
    void vscode.window.showInformationMessage(
      'No PatchAI finding at the cursor. Run "PatchAI: Scan Workspace for Vulnerabilities", then put the cursor on an underlined line.',
    );
    return undefined;
  }
  if (here.length === 1) {
    return here[0];
  }
  const picked = await vscode.window.showQuickPick(
    here.map(finding => ({ label: api.findingLabel(finding), description: finding.rule_id, detail: finding.message, finding })),
    { placeHolder: 'Which finding should PatchAI fix?' },
  );
  return picked?.finding;
}

// ---------- Panel actions ----------

async function handlePanelAction(
  action: PanelAction,
  folder: vscode.WorkspaceFolder,
  result: FixResult,
  original: string,
): Promise<void> {
  try {
    switch (action) {
      case 'accept':
        await acceptFix(folder, result, original);
        break;
      case 'reject':
        await rejectFix(folder, result);
        break;
      case 'openDiff':
        await openDiff(folder, result);
        break;
      case 'fixAgain':
        closeFixPanel();
        await fixFinding(result.finding);
        break;
      case 'tryModel': {
        const model = await pickModel();
        if (model !== undefined) {
          closeFixPanel();
          await fixFinding(result.finding, model);
        }
        break;
      }
    }
  } catch (error) {
    void findings.showError(error);
  }
}

/**
 * Applies the verified fix: the decision is logged first (so a server restart cannot lose
 * it after the file changed), the file is only replaced when it still matches what the fix
 * was made from, and an Undo button restores the original.
 */
async function acceptFix(folder: vscode.WorkspaceFolder, result: FixResult, original: string): Promise<void> {
  const newText = result.patched_file_text;
  if (result.verdict !== 'fixed' || newText === null) {
    return; // the Accept button is disabled in this case
  }
  const uri = findings.findingUri(folder, result.finding);
  const fileName = result.finding.file_path;
  const document = await vscode.workspace.openTextDocument(uri);

  // The stale check: the document (saved or not) must still be what the fix was made from.
  if (normalizeEol(document.getText()) !== normalizeEol(original)) {
    const answer = await vscode.window.showWarningMessage(
      `${fileName} changed after the fix was made. PatchAI will not overwrite your edits.`,
      { modal: true },
      'Fix again',
    );
    if (answer === 'Fix again') {
      closeFixPanel();
      await fixFinding(result.finding);
    }
    return;
  }

  const edit = new vscode.WorkspaceEdit();
  const wholeFile = new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length));
  edit.replace(uri, wholeFile, newText);
  if (!(await vscode.workspace.applyEdit(edit))) {
    throw new Error(`PatchAI could not edit ${fileName}.`);
  }
  if (!(await document.save())) {
    throw new Error(`PatchAI changed ${fileName} but could not save it.`);
  }

  // Log the decision in its own try: the fix is already applied either way.
  try {
    await api.sendDecision(folder.uri.fsPath, result.finding.id, 'approved', null, result.model);
  } catch {
    void vscode.window.showWarningMessage('The fix was applied, but the decision could not be logged.');
  }
  closeFixPanel();

  const line = Math.max(result.finding.start_line - 1, 0);
  await vscode.window.showTextDocument(document, {
    viewColumn: vscode.ViewColumn.One,
    selection: new vscode.Range(line, 0, line, 0),
  });
  void vscode.window.showInformationMessage(`Fix applied to ${fileName}.`, 'Undo').then(async choice => {
    if (choice === 'Undo') {
      await restore(uri, original);
      await findings.scanWorkspace(true);
    }
  });
  await findings.scanWorkspace(true);
}

async function restore(uri: vscode.Uri, original: string): Promise<void> {
  const document = await vscode.workspace.openTextDocument(uri);
  const edit = new vscode.WorkspaceEdit();
  const wholeFile = new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length));
  edit.replace(uri, wholeFile, original);
  await vscode.workspace.applyEdit(edit);
  await document.save();
  void vscode.window.showInformationMessage('The fix was undone.');
}

function normalizeEol(text: string): string {
  return text.replace(/\r\n/g, '\n');
}

async function rejectFix(folder: vscode.WorkspaceFolder, result: FixResult): Promise<void> {
  const reason = await askRejectReason();
  if (!reason) {
    return; // cancelled: keep the panel open
  }
  await api.sendDecision(folder.uri.fsPath, result.finding.id, 'rejected', reason, result.model);
  closeFixPanel();
  void vscode.window.showInformationMessage(`Fix rejected. Reason saved: "${reason}".`);
}

function askRejectReason(): Promise<string | undefined> {
  return new Promise(resolve => {
    const pick = vscode.window.createQuickPick();
    pick.title = 'Why are you rejecting this fix?';
    pick.placeholder = 'Pick a reason or type your own (required)';
    const suggestions = REJECT_REASONS.map(label => ({ label }));
    pick.items = suggestions;

    pick.onDidChangeValue(value => {
      const typed = value.trim();
      pick.items = typed && !REJECT_REASONS.includes(typed)
        ? [{ label: typed, description: 'your reason' }, ...suggestions]
        : suggestions;
    });
    pick.onDidAccept(() => {
      const reason = (pick.selectedItems[0]?.label ?? pick.value).trim();
      if (reason) {
        resolve(reason);
        pick.hide();
      }
    });
    pick.onDidHide(() => {
      resolve(undefined);
      pick.dispose();
    });
    pick.show();
  });
}

async function openDiff(folder: vscode.WorkspaceFolder, result: FixResult): Promise<void> {
  if (result.patched_file_text === null) {
    return;
  }
  const originalUri = findings.findingUri(folder, result.finding);
  const key = `${result.finding.id}-${++diffCounter}`;
  proposedTexts.set(key, result.patched_file_text);
  const proposedUri = originalUri.with({ scheme: PROPOSED_SCHEME, query: key });
  await vscode.commands.executeCommand(
    'vscode.diff',
    originalUri,
    proposedUri,
    `PatchAI fix: ${path.posix.basename(result.finding.file_path)}`,
    { viewColumn: vscode.ViewColumn.One },
  );
}

// ---------- Model selection ----------

export function configuredModel(): string | null {
  return vscode.workspace.getConfiguration('patchai').get<string>('model', '').trim() || null;
}

/** A quick pick of the installed models. Returns undefined when cancelled, '' for the default. */
async function pickModel(): Promise<string | null | undefined> {
  let health: api.Health;
  try {
    health = await api.getHealth();
  } catch (error) {
    void findings.showError(error);
    return undefined;
  }
  const items: (vscode.QuickPickItem & { model: string })[] = [
    { label: 'Server default', description: api.modelLabel(health.default_model), model: '' },
    ...health.models.map(model => ({
      label: api.modelLabel(model),
      description: model === health.default_model ? `${model} · server default` : model,
      model,
    })),
  ];
  const picked = await vscode.window.showQuickPick(items, { title: 'Run the fix again with…' });
  if (!picked) {
    return undefined;
  }
  return picked.model || null;
}

export async function selectModel(): Promise<void> {
  let health: api.Health;
  try {
    health = await api.getHealth();
  } catch (error) {
    void findings.showError(error);
    return;
  }
  const current = configuredModel();
  const items: (vscode.QuickPickItem & { model: string })[] = [
    { label: 'Server default', description: api.modelLabel(health.default_model) + (current === null ? ' · ✓ selected' : ''), model: '' },
    ...health.models.map(model => ({
      label: api.modelLabel(model),
      description: [model, model === health.default_model ? 'server default' : '', model === current ? '✓ selected' : '']
        .filter(Boolean)
        .join(' · '),
      model,
    })),
  ];
  const picked = await vscode.window.showQuickPick(items, {
    title: 'PatchAI model',
    placeHolder: `Choose the model that writes fixes (now: ${current ?? `server default, ${health.default_model}`})`,
  });
  if (!picked) {
    return;
  }
  const target = vscode.workspace.workspaceFolders ? vscode.ConfigurationTarget.Workspace : vscode.ConfigurationTarget.Global;
  await vscode.workspace.getConfiguration('patchai').update('model', picked.model, target);
  void findings.refreshModelStatus();
  void vscode.window.showInformationMessage(
    picked.model ? `PatchAI will use ${api.modelLabel(picked.model)}.` : `PatchAI will use the server default (${api.modelLabel(health.default_model)}).`,
  );
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
