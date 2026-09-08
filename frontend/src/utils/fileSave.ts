import { invoke, isTauri } from '@tauri-apps/api/core';

export interface SavedFile {
  path?: string;
}

export interface SaveFileOptions {
  suggestedName: string;
  extension: 'csv' | 'png';
  mimeType: 'text/csv' | 'image/png';
  description: string;
}

interface WritableFile {
  write(data: Blob): Promise<void>;
  close(): Promise<void>;
}

interface FileHandle {
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

async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const chunkSize = 0x8000;
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function pngBlobFromDataUrl(dataUrl: string): Blob {
  const match = /^data:image\/png;base64,([A-Za-z0-9+/=]+)$/i.exec(dataUrl);
  if (!match) throw new Error('图表图片数据无效');
  const binary = atob(match[1]);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return new Blob([bytes], { type: 'image/png' });
}

/**
 * Single entry point for every user-facing export. Desktop returns the real
 * native save path; browsers keep the same call contract with a safe fallback.
 */
export async function saveFile(blob: Blob, options: SaveFileOptions): Promise<SavedFile | null> {
  if (isTauri()) {
    const contentBase64 = await blobToBase64(blob);
    const path = await invoke<string | null>('save_export_file', {
      suggestedName: options.suggestedName,
      extension: options.extension,
      contentBase64,
    });
    return path ? { path } : null;
  }

  const picker = (window as SaveFilePickerWindow).showSaveFilePicker;
  if (!picker) {
    triggerDownload(blob, options.suggestedName);
    return { path: undefined };
  }

  try {
    const handle = await picker({
      suggestedName: options.suggestedName,
      types: [{ description: options.description, accept: { [options.mimeType]: [`.${options.extension}`] } }],
    });
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
    return { path: undefined };
  } catch (error) {
    if (isPickerCancellation(error)) return null;
    throw error;
  }
}

export function saveCsvFile(csv: string, suggestedName: string): Promise<SavedFile | null> {
  return saveFile(new Blob([csv], { type: 'text/csv;charset=utf-8' }), {
    suggestedName,
    extension: 'csv',
    mimeType: 'text/csv',
    description: 'CSV 文件',
  });
}

export function savePngDataUrl(dataUrl: string, suggestedName: string): Promise<SavedFile | null> {
  return saveFile(pngBlobFromDataUrl(dataUrl), {
    suggestedName,
    extension: 'png',
    mimeType: 'image/png',
    description: 'PNG 图片',
  });
}
