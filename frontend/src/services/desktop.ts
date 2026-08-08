import { invoke, isTauri } from '@tauri-apps/api/core';

export interface DesktopRuntimeConfig {
  apiBase: string;
  localToken: string;
  appVersion: string;
}

export interface DesktopUpdateInfo {
  enabled?: boolean;
  available: boolean;
  version?: string;
  notes?: string;
  notesUrl?: string;
  message?: string;
}

export type CloseAction = 'exit' | 'tray' | 'cancel';

interface CloseRequestDetail {
  requestId?: string;
}

let runtimeConfig: DesktopRuntimeConfig | null = null;
let desktopBootstrap: Promise<DesktopRuntimeConfig | null> | null = null;

export function isDesktopRuntime(): boolean {
  return isTauri();
}

export function getDesktopRuntimeConfig(): DesktopRuntimeConfig | null {
  return runtimeConfig;
}

export function initializeDesktopRuntime(): Promise<DesktopRuntimeConfig | null> {
  if (!desktopBootstrap) {
    desktopBootstrap = !isDesktopRuntime()
      ? Promise.resolve(null)
      : invoke<DesktopRuntimeConfig>('runtime_config').then(config => {
          runtimeConfig = config;
          return config;
        });
  }
  return desktopBootstrap;
}

export function checkForUpdates(): Promise<DesktopUpdateInfo> {
  return invoke<DesktopUpdateInfo>('check_for_updates');
}

export function downloadUpdate(): Promise<void> {
  return invoke<void>('download_update');
}

export function installDownloadedUpdate(): Promise<void> {
  return invoke<void>('install_update');
}

export function respondToCloseRequest(action: CloseAction, requestId?: string): Promise<void> {
  return invoke<void>('resolve_close_request', { action, requestId });
}

export function onCloseRequested(listener: (requestId?: string) => void): () => void {
  const handler = (event: Event) => listener((event as CustomEvent<CloseRequestDetail>).detail?.requestId);
  window.addEventListener('bili:close-requested', handler);
  return () => window.removeEventListener('bili:close-requested', handler);
}
