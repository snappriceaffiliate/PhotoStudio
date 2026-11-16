/** An in-memory folder that behaves like the browser's folder handles, for tests. */
import { File as StreamingFile } from 'node:buffer';
import type { DirHandleLike, FileHandleLike } from '../fs.ts';

const notFound = (name: string) => new DOMException(`${name} was not found`, 'NotFoundError');

export class MemFile implements FileHandleLike {
  readonly kind = 'file' as const;
  data: Uint8Array;
  /** Test hook: make the writable drop this many bytes, to simulate a bad copy. */
  dropBytes = 0;
  /** Test hook: make reading the file fail. */
  failRead = false;

  readonly name: string;

  constructor(name: string, data: Uint8Array | string = new Uint8Array()) {
    this.name = name;
    this.data = typeof data === 'string' ? new TextEncoder().encode(data) : data;
  }

  async getFile(): Promise<File> {
    // Node's File can stream, as a browser's can; the simulated browser's cannot.
    const file = new StreamingFile([this.data], this.name) as unknown as File;
    if (this.failRead) {
      Object.defineProperty(file, 'stream', {
        value: () =>
          new ReadableStream({
            pull(controller) {
              controller.error(new Error('The disk could not be read'));
            },
          }),
      });
    }
    return file;
  }

  async createWritable(): Promise<WritableStream<Uint8Array>> {
    const chunks: Uint8Array[] = [];
    return new WritableStream<Uint8Array>({
      write: (chunk) => {
        chunks.push(chunk);
      },
      close: () => {
        const all = new Uint8Array(chunks.reduce((n, c) => n + c.byteLength, 0));
        let offset = 0;
        for (const c of chunks) {
          all.set(c, offset);
          offset += c.byteLength;
        }
        this.data = this.dropBytes ? all.slice(0, all.byteLength - this.dropBytes) : all;
      },
    });
  }
}

export class MemDir implements DirHandleLike {
  readonly kind = 'directory' as const;
  readonly children = new Map<string, MemFile | MemDir>();
  /** Test hook: files created with these names will lose bytes when written. */
  dropBytesFor = new Set<string>();

  readonly name: string;

  constructor(name: string) {
    this.name = name;
  }

  async *entries(): AsyncIterable<[string, MemFile | MemDir]> {
    for (const entry of [...this.children]) yield entry;
  }

  async getDirectoryHandle(name: string, options: { create?: boolean } = {}): Promise<MemDir> {
    const existing = this.children.get(name);
    if (existing instanceof MemDir) return existing;
    if (existing) throw new DOMException(`${name} is a file`, 'TypeMismatchError');
    if (!options.create) throw notFound(name);
    const dir = new MemDir(name);
    this.children.set(name, dir);
    return dir;
  }

  async getFileHandle(name: string, options: { create?: boolean } = {}): Promise<MemFile> {
    const existing = this.children.get(name);
    if (existing instanceof MemFile) return existing;
    if (existing) throw new DOMException(`${name} is a folder`, 'TypeMismatchError');
    if (!options.create) throw notFound(name);
    const file = new MemFile(name);
    if (this.dropBytesFor.has(name)) file.dropBytes = 1;
    this.children.set(name, file);
    return file;
  }

  async removeEntry(name: string): Promise<void> {
    if (!this.children.delete(name)) throw notFound(name);
  }

  // Helpers for building a tree in a test.
  dir(path: string): MemDir {
    return path
      .split('/')
      .filter(Boolean)
      .reduce<MemDir>((dir, segment) => {
        const next = dir.children.get(segment);
        if (next instanceof MemDir) return next;
        const created = new MemDir(segment);
        dir.children.set(segment, created);
        return created;
      }, this);
  }

  put(path: string, data: Uint8Array | string = 'x'): MemFile {
    const parts = path.split('/');
    const name = parts.pop()!;
    const file = new MemFile(name, data);
    this.dir(parts.join('/')).children.set(name, file);
    return file;
  }

  /** The file or folder at a path, or undefined. */
  find(path: string): MemFile | MemDir | undefined {
    return path
      .split('/')
      .filter(Boolean)
      .reduce<MemFile | MemDir | undefined>((current, segment) => (current instanceof MemDir ? current.children.get(segment) : undefined), this);
  }

  /** Every file below, as "folder/name", sorted. */
  list(prefix = ''): string[] {
    const out: string[] = [];
    for (const [name, child] of this.children) {
      const path = prefix ? `${prefix}/${name}` : name;
      if (child instanceof MemDir) out.push(...child.list(path));
      else out.push(path);
    }
    return out.sort();
  }
}
