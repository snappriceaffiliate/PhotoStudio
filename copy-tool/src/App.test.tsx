// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import App from './App.tsx';
import { readSelection } from './csv.ts';
import { NotSignedInError } from './source.ts';
import type { DirHandleLike } from './fs.ts';
import { MemDir, MemFile } from './test/memfs.ts';

afterEach(cleanup);

const HEADER = 'number,folder,filename,path,album,note,selected_at,photo_id';
const csv = (...rows: [string, string][]) =>
  `﻿${HEADER}\r\n${rows.map(([f, n], i) => `${i + 1},${f},${n},${f ? `${f}/` : ''}${n},,,2026-12-01 10:00,p${i}`).join('\r\n')}\r\n`;

function eventFolder() {
  const root = new MemDir('Priya Wedding');
  root.put('Ceremony/IMG_0001.CR3', 'raw-1');
  root.put('Ceremony/IMG_0001.JPG', 'jpg-1');
  root.put('Ceremony/IMG_0002.CR3', 'raw-2');
  root.put('IMG_9000.JPG', 'top');
  return root;
}

function chooseCsv(text: string, name = 'wedding-selection.csv') {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File([text], name, { type: 'text/csv' })] } });
}

const button = (name: string | RegExp) => screen.getByRole('button', { name }) as HTMLButtonElement;

describe('the copy tool', () => {
  it('walks through the three steps and copies the photos', async () => {
    const root = eventFolder();
    render(<App supported pick={async () => root as unknown as DirHandleLike} />);

    expect(button('Choose folder').disabled).toBe(true); // needs the list first
    chooseCsv(csv(['Ceremony', 'IMG_0001.CR3'], ['', 'IMG_9000.JPG']));
    expect(await screen.findByText(/2 photos chosen/)).toBeTruthy();

    fireEvent.click(button('Choose folder'));
    expect(await screen.findByText(/Found/)).toBeTruthy();
    expect(screen.getByText('2 of 2')).toBeTruthy();

    fireEvent.click(button('Copy 3 files'));
    expect(await screen.findByText(/Done\. 3 files/)).toBeTruthy();
    expect((root.find('Selected') as MemDir).list()).toEqual(['Ceremony/IMG_0001.CR3', 'Ceremony/IMG_0001.JPG', 'IMG_9000.JPG']);
    expect(new TextDecoder().decode((root.find('Selected/IMG_9000.JPG') as MemFile).data)).toBe('top');
    expect(root.list().filter((p) => !p.startsWith('Selected/')).length).toBe(4); // originals untouched
  });

  it('says what was not found and offers the list', async () => {
    render(<App supported pick={async () => eventFolder() as unknown as DirHandleLike} />);
    chooseCsv(csv(['Ceremony', 'IMG_0001.CR3'], ['Ceremony', 'IMG_0500.CR3'], ['Nowhere', 'IMG_1.CR3']));
    await screen.findByText(/3 photos chosen/);
    fireEvent.click(button('Choose folder'));
    expect(await screen.findByText(/2 photos were not found/)).toBeTruthy();
    expect(screen.getByText('Ceremony/IMG_0500.CR3')).toBeTruthy();
    expect(screen.getByText('no file with this name')).toBeTruthy();
    expect(screen.getByText('folder not found')).toBeTruthy();
    fireEvent.click(button('Copy 2 files'));
    await screen.findByText(/Done\./);
    expect(button('Download list of problems')).toBeTruthy();
  });

  it('suggests the folder inside when the parent was picked', async () => {
    const parent = new MemDir('Weddings');
    parent.children.set('Priya Wedding', eventFolder());
    render(<App supported pick={async () => parent as unknown as DirHandleLike} />);
    chooseCsv(csv(['Ceremony', 'IMG_0001.CR3']));
    await screen.findByText(/1 photo chosen/);
    fireEvent.click(button('Choose folder'));
    expect(await screen.findByText(/None of the photos were found/)).toBeTruthy();
    expect(screen.getByText(/Did you mean the folder/).textContent).toContain('Priya Wedding');
    expect(screen.queryByRole('button', { name: /^Copy \d+ files$/ })).toBeNull();
  });

  it('refuses a file that is not a selection list', async () => {
    render(<App supported pick={async () => eventFolder() as unknown as DirHandleLike} />);
    chooseCsv('name,email\nA,a@example.com\n');
    expect((await screen.findByRole('alert')).textContent).toMatch(/does not look like a PickSnap selection file/);
    expect(button('Choose folder').disabled).toBe(true);
  });

  it('stays quiet when the folder picker is closed without choosing', async () => {
    render(<App supported pick={async () => { throw new DOMException('closed', 'AbortError'); }} />);
    chooseCsv(csv(['', 'IMG_9000.JPG']));
    await screen.findByText(/1 photo chosen/);
    fireEvent.click(button('Choose folder'));
    await waitFor(() => expect(button('Choose folder').disabled).toBe(false));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows the reason when a folder cannot be opened', async () => {
    render(<App supported pick={async () => { throw new Error('Access denied'); }} />);
    chooseCsv(csv(['', 'IMG_9000.JPG']));
    await screen.findByText(/1 photo chosen/);
    fireEvent.click(button('Choose folder'));
    expect((await screen.findByRole('alert')).textContent).toMatch(/Could not open that folder: Access denied/);
  });

  it('starts again from the beginning', async () => {
    render(<App supported pick={async () => eventFolder() as unknown as DirHandleLike} />);
    chooseCsv(csv(['', 'IMG_9000.JPG']));
    await screen.findByText(/1 photo chosen/);
    fireEvent.click(button('Choose folder'));
    fireEvent.click(await screen.findByRole('button', { name: 'Copy 1 file' }));
    await screen.findByText(/Done\./);
    fireEvent.click(button('Start again'));
    expect(screen.queryByText(/1 photo chosen/)).toBeNull();
    expect(button('Choose CSV file')).toBeTruthy();
  });

  it('explains when the browser cannot copy into folders', () => {
    render(<App supported={false} />);
    expect(screen.getByRole('alert').textContent).toMatch(/Chrome or Edge on a computer/);
    chooseCsv(csv(['', 'IMG_9000.JPG']));
    expect(button('Choose folder').disabled).toBe(true);
  });

  it('always promises that nothing is uploaded and originals are not changed', () => {
    render(<App supported />);
    expect(screen.getByText(/Nothing is uploaded/)).toBeTruthy();
    expect(screen.getByText(/never changed or deleted/)).toBeTruthy();
  });
});

describe('opened from an event in PickSnap', () => {
  const EVENT = 'ef0f1067-1a18-4cc6-a2f9-7818e960b313';
  const fromPickSnap = async () => ({
    ...readSelection('s.txt', 'Ceremony/IMG_0001.CR3\nIMG_9000.JPG'),
    title: 'Priya Wedding',
  });

  it('loads the client’s selection by itself and goes straight to choosing the folder', async () => {
    const root = eventFolder();
    render(<App supported eventId={EVENT} loadEvent={fromPickSnap} pick={async () => root as unknown as DirHandleLike} />);

    expect(await screen.findByText(/Loaded from PickSnap/)).toBeTruthy();
    expect(screen.getByText(/2 photos chosen/)).toBeTruthy();
    expect(button('Choose folder').disabled).toBe(false); // no CSV needed

    fireEvent.click(button('Choose folder'));
    fireEvent.click(await screen.findByRole('button', { name: 'Copy 3 files' }));
    expect(await screen.findByText(/Done\. 3 files/)).toBeTruthy();
    expect((root.find('Selected') as MemDir).list()).toEqual(['Ceremony/IMG_0001.CR3', 'Ceremony/IMG_0001.JPG', 'IMG_9000.JPG']);
  });

  it('says to log in to PickSnap when the studio is not signed in', async () => {
    const signedOut = async () => { throw new NotSignedInError('You are not logged in to PickSnap in this browser.'); };
    render(<App supported eventId={EVENT} loadEvent={signedOut} />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/not logged in to PickSnap/);
    expect(alert.textContent).toMatch(/log in, then click the button on the event page again/);
    expect(screen.getByRole('link', { name: 'PickSnap' }).getAttribute('href')).toBe('/');
    expect(button('Choose folder').disabled).toBe(true);
  });

  it('shows other problems plainly and still allows a CSV', async () => {
    const failing = async () => { throw new Error('boom'); };
    render(<App supported eventId={EVENT} loadEvent={failing} pick={async () => eventFolder() as unknown as DirHandleLike} />);
    expect((await screen.findByRole('alert')).textContent).toMatch(/could not be loaded from PickSnap/);
    chooseCsv(csv(['', 'IMG_9000.JPG']));
    expect(await screen.findByText(/1 photo chosen/)).toBeTruthy();
    expect(button('Choose folder').disabled).toBe(false);
  });

  it('can swap to a CSV file, and start again brings the event’s selection back', async () => {
    render(<App supported eventId={EVENT} loadEvent={fromPickSnap} pick={async () => eventFolder() as unknown as DirHandleLike} />);
    await screen.findByText(/Loaded from PickSnap/);
    chooseCsv(csv(['', 'IMG_9000.JPG']));
    expect(await screen.findByText(/1 photo chosen/)).toBeTruthy();
    expect(screen.queryByText(/Loaded from PickSnap/)).toBeNull();

    fireEvent.click(button('Choose folder'));
    fireEvent.click(await screen.findByRole('button', { name: 'Copy 1 file' }));
    await screen.findByText(/Done\./);
    fireEvent.click(button('Start again'));
    expect(await screen.findByText(/Loaded from PickSnap/)).toBeTruthy();
  });

  it('does not offer a loading step when it was opened without an event', () => {
    render(<App supported eventId={null} />);
    expect(screen.queryByText(/Loading the client/)).toBeNull();
    expect(button('Choose CSV file')).toBeTruthy();
  });
});
