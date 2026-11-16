import { describe, expect, it } from 'vitest';
import { selectionFromRows, SelectionFileError } from './csv.ts';
import { eventIdFromAddress, loadEventSelection, NotSignedInError } from './source.ts';

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function server(routes: Record<string, () => Response>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fake = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    const route = routes[String(input)];
    return route ? route() : json({ detail: 'missing' }, 404);
  }) as typeof fetch;
  return { fake, calls };
}

const ID = 'ef0f1067-1a18-4cc6-a2f9-7818e960b313';

describe('loadEventSelection', () => {
  it('reads the event name and the chosen photos with the studio’s login', async () => {
    const { fake, calls } = server({
      [`/api/v1/events/${ID}`]: () => json({ title: 'Priya and Arun Wedding' }),
      [`/api/v1/events/${ID}/selection`]: () =>
        json({
          count: 3,
          results: [
            { relative_path: 'Ceremony/IMG_0001.CR3', note: 'Album cover', album: 'Ceremony' },
            { relative_path: 'IMG_9000.JPG', note: '', album: '' },
            { relative_path: 'Ceremony/IMG_0001.JPG', note: '', album: '' },
          ],
        }),
    });
    const result = await loadEventSelection(ID, fake);
    expect(result.title).toBe('Priya and Arun Wedding');
    expect(result.photos.map((p) => [...p.folder, p.filename].join('/'))).toEqual(['Ceremony/IMG_0001.CR3', 'IMG_9000.JPG']);
    expect(result.duplicates).toBe(1); // the JPEG next to the RAW is the same chosen photo
    expect(result.photos[0].note).toBe('Album cover');
    expect(calls.every((c) => c.init?.credentials === 'same-origin')).toBe(true);
  });

  it('keeps a real name that starts with a quote and a dash', async () => {
    const { fake } = server({
      [`/api/v1/events/${ID}`]: () => json({ title: 'E' }),
      [`/api/v1/events/${ID}/selection`]: () => json({ results: [{ relative_path: "'-odd/'=x.jpg" }] }),
    });
    const [photo] = (await loadEventSelection(ID, fake)).photos;
    expect(photo.folder).toEqual(["'-odd"]);
    expect(photo.filename).toBe("'=x.jpg");
  });

  it('says to log in when PickSnap refuses', async () => {
    const { fake } = server({
      [`/api/v1/events/${ID}`]: () => json({ detail: 'no' }, 403),
      [`/api/v1/events/${ID}/selection`]: () => json({ detail: 'no' }, 403),
    });
    await expect(loadEventSelection(ID, fake)).rejects.toBeInstanceOf(NotSignedInError);
  });

  it('says so for an unknown event, a server error and a dead network', async () => {
    await expect(loadEventSelection(ID, server({}).fake)).rejects.toThrow(/could not be found/);
    const broken = server({ [`/api/v1/events/${ID}`]: () => json({}, 500), [`/api/v1/events/${ID}/selection`]: () => json({}, 500) });
    await expect(loadEventSelection(ID, broken.fake)).rejects.toThrow(/error 500/);
    const offline = (async () => { throw new TypeError('offline'); }) as typeof fetch;
    await expect(loadEventSelection(ID, offline)).rejects.toThrow(/Could not reach PickSnap/);
  });

  it('says so when the client has not chosen anything', async () => {
    const { fake } = server({
      [`/api/v1/events/${ID}`]: () => json({ title: 'E' }),
      [`/api/v1/events/${ID}/selection`]: () => json({ count: 0, results: [] }),
    });
    await expect(loadEventSelection(ID, fake)).rejects.toThrow(/has not chosen any photos/);
  });
});

describe('eventIdFromAddress', () => {
  it('takes a plain id from the address', () => {
    expect(eventIdFromAddress(`?event=${ID}`)).toBe(ID);
  });

  it('ignores anything else', () => {
    expect(eventIdFromAddress('')).toBeNull();
    expect(eventIdFromAddress('?event=')).toBeNull();
    expect(eventIdFromAddress('?event=../../admin')).toBeNull();
    expect(eventIdFromAddress('?event=a')).toBeNull();
    expect(eventIdFromAddress('?event=%3Cscript%3E')).toBeNull();
  });
});

describe('selectionFromRows', () => {
  it('refuses a path that climbs out of the event folder', () => {
    expect(() => selectionFromRows([{ path: '../x/IMG.jpg' }])).toThrow(SelectionFileError);
  });
});
