import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { api, ApiError } from '../api/client';
import { FormMessage } from '../components/Form';

/** One photo on this page, from either the photo list or the client's selection. */
interface Tile {
  id: string;
  path: string;
  name: string;
  thumb: string | null;
  preview: string | null;
  chosen: boolean;
  note: string;
  time: string;
}

interface ListPhoto {
  id: string;
  relative_path: string;
  original_filename: string;
  chosen: boolean;
  created_at: string;
  thumb_url: string;
  preview_url: string;
}

interface ChosenPhoto {
  photo_id: string;
  relative_path: string;
  filename: string;
  note: string;
  selected_at: string;
  thumb_url: string | null;
  preview_url: string | null;
}

interface Album {
  id: string;
  name: string;
}

const PAGE_SIZE = 60;
const DELETE_PER_CALL = 500;

const SORTS = [
  { value: '', label: 'Upload order' },
  { value: 'name', label: 'File name A to Z' },
  { value: '-name', label: 'File name Z to A' },
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
];

const fromList = (p: ListPhoto): Tile => ({
  id: p.id, path: p.relative_path, name: p.original_filename, thumb: p.thumb_url, preview: p.preview_url,
  chosen: p.chosen, note: '', time: p.created_at,
});

const fromChosen = (p: ChosenPhoto): Tile => ({
  id: p.photo_id, path: p.relative_path, name: p.filename, thumb: p.thumb_url, preview: p.preview_url,
  chosen: true, note: p.note, time: p.selected_at,
});

/** The client's choices come as one list; sort them here the same way the server sorts photos. */
function sortChosen(tiles: Tile[], sort: string): Tile[] {
  const sorted = [...tiles];
  if (sort === 'name' || sort === '-name') sorted.sort((a, b) => a.path.localeCompare(b.path, undefined, { numeric: true }));
  if (sort === '-name') sorted.reverse();
  if (sort === 'newest' || sort === 'oldest') sorted.sort((a, b) => a.time.localeCompare(b.time));
  if (sort === 'newest') sorted.reverse();
  return sorted;
}

/** Every photo of an event, or every photo the client chose: sort them, look at them, delete some. */
export function EventPhotosPage() {
  const { eventId } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') === 'chosen' ? 'chosen' : 'all';
  const [title, setTitle] = useState('');
  const [albums, setAlbums] = useState<Album[]>([]);
  const [sort, setSort] = useState('');
  const [album, setAlbum] = useState('');
  const [tiles, setTiles] = useState<Tile[] | null>(null);
  const [total, setTotal] = useState(0);
  const [chosenTotal, setChosenTotal] = useState(0);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Tile | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    api<{ title: string }>(`/events/${eventId}`).then((e) => setTitle(e.title)).catch(() => setError('This event could not be found.'));
    api<Album[]>(`/events/${eventId}/albums`).then(setAlbums).catch(() => undefined);
  }, [eventId]);

  // The count of chosen photos, for the tab label, whichever tab is open.
  useEffect(() => {
    api<{ count: number }>(`/events/${eventId}/selection`).then((s) => setChosenTotal(s.count)).catch(() => undefined);
  }, [eventId, version]);

  useEffect(() => {
    let current = true;
    setPicked(new Set());
    if (tab === 'chosen') {
      api<{ count: number; results: ChosenPhoto[] }>(`/events/${eventId}/selection`)
        .then((s) => {
          if (!current) return;
          setTiles(sortChosen(s.results.map(fromChosen), sort));
          setTotal(s.count);
          setNextPage(null);
        })
        .catch(() => current && setError('Could not load the photos.'));
    } else {
      const query = `page=1&page_size=${PAGE_SIZE}${sort ? `&sort=${sort}` : ''}${album ? `&album=${album}` : ''}`;
      api<{ count: number; next_page: number | null; results: ListPhoto[] }>(`/events/${eventId}/photos?${query}`)
        .then((page) => {
          if (!current) return;
          setTiles(page.results.map(fromList));
          setTotal(page.count);
          setNextPage(page.next_page);
        })
        .catch(() => current && setError('Could not load the photos.'));
    }
    return () => {
      current = false;
    };
  }, [eventId, tab, sort, album, version]);

  async function loadMore() {
    if (!nextPage) return;
    const query = `page=${nextPage}&page_size=${PAGE_SIZE}${sort ? `&sort=${sort}` : ''}${album ? `&album=${album}` : ''}`;
    const page = await api<{ next_page: number | null; results: ListPhoto[] }>(`/events/${eventId}/photos?${query}`);
    setTiles((t) => [...(t ?? []), ...page.results.map(fromList)]);
    setNextPage(page.next_page);
  }

  function toggle(id: string) {
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function deletePicked() {
    const ids = [...picked];
    const chosen = (tiles ?? []).filter((t) => picked.has(t.id) && t.chosen).length;
    const question =
      `Delete ${ids.length} ${ids.length === 1 ? 'photo' : 'photos'}? The client will no longer see ${ids.length === 1 ? 'it' : 'them'}.` +
      (chosen ? ` ${chosen} of them ${chosen === 1 ? 'was' : 'were'} chosen by the client and will be removed from the selection.` : '') +
      ' Your original photos on your computer are not touched. This cannot be undone.';
    if (!window.confirm(question)) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      let deleted = 0;
      let removed = 0;
      for (let i = 0; i < ids.length; i += DELETE_PER_CALL) {
        const result = await api<{ deleted: number; removed_from_selection: number }>(`/events/${eventId}/photos/delete`, {
          method: 'POST',
          body: { photo_ids: ids.slice(i, i + DELETE_PER_CALL) },
        });
        deleted += result.deleted;
        removed += result.removed_from_selection;
      }
      setNotice(
        `Deleted ${deleted} ${deleted === 1 ? 'photo' : 'photos'}.` +
          (removed ? ` ${removed} ${removed === 1 ? 'was' : 'were'} removed from the client’s selection.` : ''),
      );
      setVersion((v) => v + 1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not delete the photos.');
    } finally {
      setBusy(false);
    }
  }

  const shown = tiles ?? [];
  const allPicked = shown.length > 0 && shown.every((t) => picked.has(t.id));

  return (
    <>
      <p className="crumbs">
        <Link to="/events">Events</Link> / <Link to={`/events/${eventId}`}>{title || 'Event'}</Link> / Photos
      </p>
      <div className="page-header">
        <h1>Photos</h1>
        <Link className="button secondary" to={`/events/${eventId}`}>Back to the event</Link>
      </div>

      <div className="photos-toolbar">
        <div className="tabs" role="tablist" aria-label="Which photos">
          <button role="tab" aria-selected={tab === 'all'} className={tab === 'all' ? 'tab active' : 'tab'}
            onClick={() => setParams({})}>
            All photos{tab === 'all' && tiles ? ` (${total})` : ''}
          </button>
          <button role="tab" aria-selected={tab === 'chosen'} className={tab === 'chosen' ? 'tab active' : 'tab'}
            onClick={() => setParams({ tab: 'chosen' })}>
            Chosen by client ({chosenTotal})
          </button>
        </div>
        <label className="inline-select">
          Sort
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </label>
        {tab === 'all' && albums.length > 0 && (
          <label className="inline-select">
            Album
            <select value={album} onChange={(e) => setAlbum(e.target.value)}>
              <option value="">All albums</option>
              {albums.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              <option value="none">Not in an album</option>
            </select>
          </label>
        )}
      </div>

      <FormMessage error={error} success={notice} />

      {shown.length > 0 && (
        <div className="select-bar">
          <button type="button" className="link" onClick={() => setPicked(allPicked ? new Set() : new Set(shown.map((t) => t.id)))}>
            {allPicked ? 'Clear selection' : `Select all ${shown.length} shown`}
          </button>
          <span className="muted">{picked.size} selected</span>
          <button type="button" className="danger-button" disabled={picked.size === 0 || busy} onClick={deletePicked}>
            {busy ? 'Deleting…' : `Delete ${picked.size || ''} ${picked.size === 1 ? 'photo' : 'photos'}`.replace('  ', ' ')}
          </button>
        </div>
      )}

      {tiles === null && !error && <p className="muted">Loading photos…</p>}
      {tiles !== null && shown.length === 0 && (
        <div className="empty"><p>{tab === 'chosen' ? 'The client has not chosen any photos yet.' : 'No photos here.'}</p></div>
      )}

      <ul className="photo-grid manage-grid">
        {shown.map((t) => (
          <li key={t.id} className={picked.has(t.id) ? 'manage-tile picked' : 'manage-tile'}>
            {t.thumb ? (
              <button type="button" className="thumb" onClick={() => setOpen(t)} title={t.path}>
                <img src={t.thumb} alt={t.name} loading="lazy" />
              </button>
            ) : (
              <div className="thumb removed" title={t.path}>{t.name}</div>
            )}
            <label className="tile-check">
              <input type="checkbox" checked={picked.has(t.id)} onChange={() => toggle(t.id)} aria-label={`Select ${t.name}`} />
            </label>
            {t.chosen && tab === 'all' && <span className="tile-badge">Chosen</span>}
            <p className="tile-name" title={t.path}>{t.name}{t.note ? ` · ${t.note}` : ''}</p>
          </li>
        ))}
      </ul>
      {nextPage && (
        <div className="actions center"><button className="secondary" onClick={loadMore}>Load more</button></div>
      )}

      {open?.preview && (
        <div className="lightbox" onClick={() => setOpen(null)}>
          <img src={open.preview} alt={open.name} />
          <p>{open.path}{open.note ? ` · Note: ${open.note}` : ''} · click to close</p>
        </div>
      )}
    </>
  );
}
