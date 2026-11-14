import { useEffect, useState } from 'react';
import { api } from '../api/client';

interface SelectedPhoto {
  photo_id: string;
  relative_path: string;
  filename: string;
  album: string;
  note: string;
  thumb_url: string | null;
  preview_url: string | null;
}

interface SelectionData {
  count: number;
  duplicate_filenames: string[];
  results: SelectedPhoto[];
}

const DOWNLOADS = [
  { type: 'script-windows', label: 'Copy script for Windows', hint: 'Put it in the event folder and double-click it.' },
  { type: 'script-mac', label: 'Copy script for Mac', hint: 'Put it in the event folder; in Terminal run: bash copy-selected.sh' },
  { type: 'lightroom', label: 'Lightroom filter text', hint: 'Paste into Library Filter › Text › Filename › Contains.' },
  { type: 'csv', label: 'Spreadsheet (CSV)', hint: 'Folder, filename, album and note for each photo.' },
  { type: 'txt', label: 'Plain list', hint: 'One file path per line.' },
];

/** The client's selection: review it and download it in the studio's preferred form. */
export function SelectionPanel({ eventId, version }: { eventId: string; version: number }) {
  const [data, setData] = useState<SelectionData | null>(null);
  const [open, setOpen] = useState<SelectedPhoto | null>(null);

  useEffect(() => {
    api<SelectionData>(`/events/${eventId}/selection`).then(setData).catch(() => setData(null));
  }, [eventId, version]);

  if (!data || data.count === 0) return null;
  const withNotes = data.results.filter((p) => p.note);

  return (
    <section className="panel">
      <h2>Client's selection <span className="muted">({data.count} photos)</span></h2>
      <p className="muted">
        The copy scripts make a <strong>Selected</strong> folder with copies of the chosen originals, including RAW and
        sidecar files with the same name. Your originals are not changed.
      </p>
      <ul className="downloads">
        {DOWNLOADS.map((d) => (
          <li key={d.type}>
            <a className="button secondary" href={`/api/v1/events/${eventId}/export?type=${d.type}`} download>{d.label}</a>
            <span className="muted">{d.hint}</span>
          </li>
        ))}
      </ul>
      {data.duplicate_filenames.length > 0 && (
        <p className="warning">
          {data.duplicate_filenames.length} selected filename{data.duplicate_filenames.length > 1 ? 's are' : ' is'} also
          used in another folder (for example {data.duplicate_filenames[0]}). The copy scripts and CSV use the folder too;
          the Lightroom filter may also match the other file.
        </p>
      )}
      {withNotes.length > 0 && (
        <>
          <h3>Notes from the client</h3>
          <ul className="plain-list">
            {withNotes.map((p) => (
              <li key={p.photo_id}><code>{p.relative_path}</code>: {p.note}</li>
            ))}
          </ul>
        </>
      )}
      <ul className="photo-grid small">
        {data.results.map((p) => (
          <li key={p.photo_id}>
            {p.thumb_url ? (
              <button className="thumb" onClick={() => setOpen(p)} title={`${p.relative_path}${p.note ? ` · ${p.note}` : ''}`}>
                <img src={p.thumb_url} alt={p.filename} loading="lazy" />
              </button>
            ) : (
              <div className="thumb removed" title={p.relative_path}>{p.filename}</div>
            )}
          </li>
        ))}
      </ul>
      {open?.preview_url && (
        <div className="lightbox" onClick={() => setOpen(null)}>
          <img src={open.preview_url} alt={open.filename} />
          <p>{open.relative_path}{open.note ? ` · Note: ${open.note}` : ''} · click to close</p>
        </div>
      )}
    </section>
  );
}

/** Archive closes the client gallery; images are removed 90 days later. */
export function ArchivePanel({ eventId, status, onChanged }: { eventId: string; status: string; onChanged: () => void }) {
  const [error, setError] = useState('');
  const archived = status === 'archived';

  async function toggle() {
    const question = archived
      ? 'Reopen this event? The client gallery opens again.'
      : 'Archive this event? The client gallery closes now, and the photo previews are deleted after 90 days. The selection list is kept.';
    if (!window.confirm(question)) return;
    setError('');
    try {
      await api(`/events/${eventId}/${archived ? 'unarchive' : 'archive'}`, { method: 'POST' });
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not change the event.');
    }
  }

  return (
    <div className="panel">
      <h2>{archived ? 'Archived' : 'Finish the event'}</h2>
      <p className="muted">
        {archived
          ? 'The client gallery is closed. Previews are deleted 90 days after archiving; the selection list stays.'
          : 'When printing is done, archive the event to close the gallery and free storage later.'}
      </p>
      {error && <p className="form-error">{error}</p>}
      <button className="secondary" onClick={toggle}>{archived ? 'Reopen event' : 'Archive event'}</button>
    </div>
  );
}
