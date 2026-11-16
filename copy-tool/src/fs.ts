/**
 * The small part of the browser's File System Access API this tool uses, written as
 * interfaces so the real folder handles fit them and the tests can use an in-memory folder.
 */

export interface FileHandleLike {
  readonly kind: 'file';
  readonly name: string;
  getFile(): Promise<File>;
  createWritable(): Promise<WritableStream<Uint8Array>>;
}

export interface DirHandleLike {
  readonly kind: 'directory';
  readonly name: string;
  entries(): AsyncIterable<[string, FileHandleLike | DirHandleLike]>;
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<DirHandleLike>;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<FileHandleLike>;
  removeEntry(name: string, options?: { recursive?: boolean }): Promise<void>;
}

/** The folder inside the event folder that receives the copies. */
export const SELECTED_DIR = 'Selected';

export function isNotFound(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'NotFoundError';
}

/** Chrome, Edge and Opera can write to a folder the user picks; Safari and Firefox cannot. */
export function canPickFolders(): boolean {
  return typeof window !== 'undefined' && window.isSecureContext && 'showDirectoryPicker' in window;
}

export async function pickFolder(): Promise<DirHandleLike> {
  const picker = (window as unknown as {
    showDirectoryPicker: (options: { id: string; mode: 'readwrite' }) => Promise<DirHandleLike>;
  }).showDirectoryPicker;
  return picker.call(window, { id: 'picksnap-originals', mode: 'readwrite' });
}
