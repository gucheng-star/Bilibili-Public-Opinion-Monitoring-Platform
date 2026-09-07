import { invoke, isTauri } from '@tauri-apps/api/core';

export interface SavedFile {
  path?: string;
}

interface WritableFile {
  write(data: Blob): Promise<void>;
  close(): Promise<void>;
}

interface FileHandle {
  name: string;
  createWritable(): Promise<WritableFile>;
}

interface SaveFilePickerWindow extends Window {
  showSaveFilePicker?: (options: {
    suggestedName: string;
    types: Array<{ description: string; accept: Record<string, string[]> }>;
  }) => Promise<FileHandle>;
}

function triggerDownload(blob: Blob, fileName: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}

function isPickerCancellation(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'name' in error && error.name === 'AbortError';
}

/**
 * Opens the browser engine's standard save dialog whenever it is available.
 * The compatibility download is intentionally kept inside this single API so
 * callers never branch by browser versus desktop runtime.
 */
export async function saveCsvFile(csv: string, suggestedName: string): Promise<SavedFile | null> {
  if (isTauri()) {
    const path = await invoke<string | null>('save_csv_file', { suggestedName, csv });
    return path ? { path } : null;
  }
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const picker = (window as SaveFilePickerWindow).showSaveFilePicker;
  if (!picker) {
    triggerDownload(blob, suggestedName);
    return {
      path: undefined,
    };
  }

  try {
    const handle = await picker({
      suggestedName,
      types: [{ description: 'CSV 文件', accept: { 'text/csv': ['.csv'] } }],
    });
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
    return {
      path: undefined,
    };
  } catch (error) {
    if (isPickerCancellation(error)) return null;
    throw error;
  }
}
