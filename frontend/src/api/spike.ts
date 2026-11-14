/** Client for the Sprint 0 storage spike endpoints (enabled only when SPIKES_ENABLED is set). */

export interface StoredImage {
  key: string;
  size: number;
  downloadUrl: string;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status}: ${JSON.stringify(data)}`);
  return data as T;
}

export async function requestUploadUrl(filename: string, contentType: string, size: number) {
  return postJson<{ key: string; upload_url: string }>('/api/v1/spike/upload-url', {
    filename,
    content_type: contentType,
    size,
  });
}

/** Signed upload straight to storage, then a server-side size check and a signed delivery URL. */
export async function uploadAndConfirm(filename: string, blob: Blob): Promise<StoredImage> {
  const { key, upload_url } = await requestUploadUrl(filename, blob.type, blob.size);
  const put = await fetch(upload_url, { method: 'PUT', body: blob, headers: { 'Content-Type': blob.type } });
  if (!put.ok) throw new Error(`Storage upload failed: ${put.status}`);
  const confirmed = await postJson<{ key: string; size: number; download_url: string }>('/api/v1/spike/confirm', { key });
  return { key: confirmed.key, size: confirmed.size, downloadUrl: confirmed.download_url };
}
