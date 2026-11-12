// server.ts: finds the PatchAI folder and its Python, starts the local server as a child
// process (its output goes to an Output channel), waits until /health answers, and stops
// only a server this window started.

import { ChildProcess, spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import * as api from './api';

let output: vscode.OutputChannel | undefined;
let serverProcess: ChildProcess | undefined;
let lastLines: string[] = [];
let globalState: vscode.Memento | undefined;

export function init(context: vscode.ExtensionContext): void {
  globalState = context.globalState;
  context.subscriptions.push(
    vscode.commands.registerCommand('patchai.startServer', () => ensureServer(true)),
    vscode.commands.registerCommand('patchai.stopServer', stopServer),
    vscode.commands.registerCommand('patchai.showServerLog', () => channel().show()),
    vscode.commands.registerCommand('patchai.setFolder', pickFolder),
    { dispose: stopServer },
  );
}

function channel(): vscode.OutputChannel {
  if (!output) {
    output = vscode.window.createOutputChannel('PatchAI Server');
  }
  return output;
}

// ---------- Finding the PatchAI folder and Python ----------

/** A folder counts as the PatchAI folder when it has both the server module and the config. */
function isPatchaiFolder(folder: string): boolean {
  return fs.existsSync(path.join(folder, 'patchai', 'server.py')) && fs.existsSync(path.join(folder, 'config.yaml'));
}

/**
 * Where PatchAI lives, first match wins:
 * the setting, the workspace folders and their parents, the extension's parent
 * (development), the folder remembered from last time, and finally - only when the
 * user started this action - a folder picker.
 */
export async function findPatchaiFolder(interactive: boolean): Promise<string | undefined> {
  const configured = vscode.workspace.getConfiguration('patchai').get<string>('serverDir', '').trim();
  if (configured && isPatchaiFolder(configured)) {
    return configured;
  }
  for (const workspace of vscode.workspace.workspaceFolders ?? []) {
    let candidate = workspace.uri.fsPath;
    for (let up = 0; up <= 4; up++) {
      if (isPatchaiFolder(candidate)) {
        return candidate;
      }
      const parent = path.dirname(candidate);
      if (parent === candidate) {
        break;
      }
      candidate = parent;
    }
  }
  const devFolder = path.dirname(extensionPath());
  if (isPatchaiFolder(devFolder)) {
    return devFolder;
  }
  const remembered = globalState?.get<string>('patchai.folder');
  if (remembered && isPatchaiFolder(remembered)) {
    return remembered;
  }
  if (interactive) {
    return pickFolder();
  }
  return undefined;
}

async function pickFolder(): Promise<string | undefined> {
  const picked = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    title: 'Select your PatchAI folder (the one with config.yaml)',
    openLabel: 'Use this folder',
  });
  const folder = picked?.[0]?.fsPath;
  if (!folder) {
    return undefined;
  }
  if (!isPatchaiFolder(folder)) {
    void vscode.window.showErrorMessage(
      `${folder} does not look like the PatchAI folder (no patchai/server.py and config.yaml).`,
    );
    return undefined;
  }
  await globalState?.update('patchai.folder', folder);
  return folder;
}

export async function rememberFolder(folder: string): Promise<void> {
  await globalState?.update('patchai.folder', folder);
}

let _extensionPath = '';
export function setExtensionPath(p: string): void {
  _extensionPath = p;
}
function extensionPath(): string {
  return _extensionPath;
}

/** The Python that runs the server: the setting, else the folder's .venv, else plain python. */
export function findPython(folder: string): string {
  const configured = vscode.workspace.getConfiguration('patchai').get<string>('pythonPath', '').trim();
  if (configured) {
    return path.isAbsolute(configured) || !/[\\/]/.test(configured)
      ? configured
      : path.resolve(folder, configured);
  }
  const venv = process.platform === 'win32'
    ? path.join(folder, '.venv', 'Scripts', 'python.exe')
    : path.join(folder, '.venv', 'bin', 'python');
  if (fs.existsSync(venv)) {
    return venv;
  }
  return process.platform === 'win32' ? 'python' : 'python3';
}

// ---------- Starting and stopping ----------

function serverPort(): string {
  try {
    return new URL(api.serverUrl()).port || '8765';
  } catch {
    return '8765';
  }
}

async function healthy(): Promise<api.Health | undefined> {
  try {
    return await api.getHealth();
  } catch {
    return undefined;
  }
}

/**
 * Makes sure a server answers /health; starts one when none does.
 * Returns the health, or undefined when it could not be started.
 */
export async function ensureServer(interactive: boolean): Promise<api.Health | undefined> {
  const already = await healthy();
  if (already) {
    return already;
  }
  const folder = await findPatchaiFolder(interactive);
  if (!folder) {
    if (interactive) {
      void vscode.window.showErrorMessage(
        'PatchAI: could not find the PatchAI folder. Set "patchai.serverDir" in the settings, ' +
        'or run "PatchAI: Set PatchAI Folder".',
      );
    }
    return undefined;
  }
  await rememberFolder(folder);
  const python = findPython(folder);
  const port = serverPort();

  stopServer(); // a previous process of this window that stopped answering
  lastLines = [];
  const log = channel();
  log.appendLine(`[extension] starting: ${python} -m uvicorn patchai.server:app --host 127.0.0.1 --port ${port}`);
  log.appendLine(`[extension] in folder: ${folder}`);
  const child = spawn(python, ['-m', 'uvicorn', 'patchai.server:app', '--host', '127.0.0.1', '--port', port], {
    cwd: folder,
  });
  serverProcess = child;
  const onData = (chunk: Buffer) => {
    const text = chunk.toString('utf8');
    log.append(text);
    lastLines = lastLines.concat(text.split(/\r?\n/).filter(Boolean)).slice(-15);
  };
  child.stdout?.on('data', onData);
  child.stderr?.on('data', onData);
  child.on('exit', code => {
    log.appendLine(`[extension] server exited with code ${code}`);
    if (serverProcess === child) {
      serverProcess = undefined;
    }
  });

  return vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'Starting PatchAI…' },
    async () => {
      for (let waited = 0; waited < 60_000; waited += 500) {
        if (child.exitCode !== null) {
          await startupFailed(folder);
          return undefined;
        }
        const health = await healthy();
        if (health) {
          return health;
        }
        await sleep(500);
      }
      void vscode.window.showErrorMessage('The PatchAI server did not answer within 60 seconds.', 'Show log')
        .then(choice => choice && channel().show());
      return undefined;
    },
  );
}

async function startupFailed(folder: string): Promise<void> {
  const tail = lastLines.slice(-4).join('\n');
  let hint = '';
  if (/No module named/i.test(tail)) {
    hint = ` Run \`pip install -r requirements.txt\` in ${folder}, or set "patchai.pythonPath".`;
  } else if (/address already in use|only one usage/i.test(tail)) {
    hint = ' Another process is using the port; stop it or change "patchai.serverUrl".';
  }
  const choice = await vscode.window.showErrorMessage(
    `The PatchAI server stopped right away.${hint}\n${tail}`.slice(0, 600),
    'Show log',
  );
  if (choice) {
    channel().show();
  }
}

/** Stops only a server this window started. */
export function stopServer(): void {
  if (serverProcess && serverProcess.exitCode === null) {
    serverProcess.kill();
  }
  serverProcess = undefined;
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
