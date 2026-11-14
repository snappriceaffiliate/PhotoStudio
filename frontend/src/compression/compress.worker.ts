import { compressFile, type CompressOptions } from './compress';

export interface WorkerRequest {
  id: number;
  file: File;
  path: string;
  options: CompressOptions;
}

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const { id, file, path, options } = event.data;
  try {
    const result = await compressFile(file, path, options);
    self.postMessage({ id, result });
  } catch (error) {
    self.postMessage({ id, error: error instanceof Error ? error.message : String(error) });
  }
};
