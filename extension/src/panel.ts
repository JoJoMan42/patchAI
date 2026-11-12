// panel.ts: the webview panel's lifecycle and message passing. What the panel shows is
// built by the pure functions in render.ts; what the buttons do lives in fix.ts.

import { randomBytes } from 'crypto';
import * as vscode from 'vscode';
import { Finding, FixEvent, FixResult, vulnerabilityName } from './api';
import { renderResult, renderWorking } from './render';

export type PanelAction = 'accept' | 'reject' | 'openDiff' | 'fixAgain' | 'tryModel';

let openPanel: vscode.WebviewPanel | undefined;
let sentEvents = 0;

/** Opens (or reuses) the panel in its working state and reports button clicks. */
export function showWorkingPanel(finding: Finding, model: string | null): void {
  const panel = freshPanel(`PatchAI: fixing ${vulnerabilityName(finding)}…`);
  sentEvents = 0;
  panel.webview.html = renderWorking(finding, model, nonce());
}

/** Streams new progress events into the working page. */
export function postEvents(events: FixEvent[]): void {
  if (openPanel && events.length > sentEvents) {
    sentEvents = events.length;
    void openPanel.webview.postMessage({ type: 'events', events });
  }
}

/** Replaces the panel's content with the finished result and wires the buttons. */
export function showResultPanel(result: FixResult, onAction: (action: PanelAction) => Promise<void>): void {
  const panel = openPanel ?? freshPanel(`PatchAI: ${vulnerabilityName(result.finding)}`);
  panel.title = `PatchAI: ${vulnerabilityName(result.finding)}`;
  panel.webview.onDidReceiveMessage(async (message: { action: PanelAction }) => {
    try {
      await onAction(message.action);
    } finally {
      // The webview locks the buttons on click; unlock them unless the action closed the panel.
      if (openPanel === panel) {
        void panel.webview.postMessage({ type: 'enableButtons' });
      }
    }
  });
  panel.webview.html = renderResult(result, nonce());
}

export function closeFixPanel(): void {
  openPanel?.dispose();
}

function freshPanel(title: string): vscode.WebviewPanel {
  openPanel?.dispose(); // one review at a time keeps the editor tidy
  const panel = vscode.window.createWebviewPanel(
    'patchai.fixResult',
    title,
    vscode.ViewColumn.Beside,
    { enableScripts: true, enableFindWidget: true, localResourceRoots: [] },
  );
  openPanel = panel;
  panel.onDidDispose(() => {
    if (openPanel === panel) {
      openPanel = undefined;
    }
  });
  return panel;
}

function nonce(): string {
  return randomBytes(16).toString('hex');
}
