/**
 * Loads a client's selection straight from PickSnap, for the "Copy selected files to local"
 * button on the event page. The page is served by PickSnap itself, so the studio's login
 * cookie is sent with these requests and no CSV needs to be downloaded and chosen again.
 */
import { selectionFromRows, SelectionFileError, type Selection } from './csv.ts';

export class NotSignedInError extends SelectionFileError {}

export interface EventSelection extends Selection {
  title: string;
}

interface ApiSelection {
  results: { relative_path: string; note?: string; album?: string }[];
}

async function getJson<T>(path: string, doFetch: typeof fetch): Promise<T> {
  let response: Response;
  try {
    response = await doFetch(path, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
  } catch {
    throw new SelectionFileError('Could not reach PickSnap. Check your connection and try again.');
  }
  if (response.status === 401 || response.status === 403) {
    throw new NotSignedInError('You are not logged in to PickSnap in this browser.');
  }
  if (response.status === 404) {
    throw new SelectionFileError('That event could not be found. Open it from your PickSnap events list.');
  }
  if (!response.ok) throw new SelectionFileError(`PickSnap could not give the selection (error ${response.status}).`);
  return (await response.json()) as T;
}

export async function loadEventSelection(eventId: string, doFetch: typeof fetch = fetch): Promise<EventSelection> {
  const id = encodeURIComponent(eventId);
  const [event, selection] = await Promise.all([
    getJson<{ title: string }>(`/api/v1/events/${id}`, doFetch),
    getJson<ApiSelection>(`/api/v1/events/${id}/selection`, doFetch),
  ]);
  const parsed = selectionFromRows(
    selection.results.map((r) => ({ path: r.relative_path, note: r.note, album: r.album })),
  );
  return { ...parsed, title: event.title };
}

/** The event id in the address (?event=...), if any. Only plain id characters are accepted. */
export function eventIdFromAddress(search: string): string | null {
  const id = new URLSearchParams(search).get('event');
  return id && /^[0-9a-zA-Z-]{8,64}$/.test(id) ? id : null;
}
