# PickSnap Copy Tool

A small web page for the photo studio's computer. You give it the selection file your client
made (the CSV from the event page), then point it at the folder with the original photos, and
it copies every chosen photo into a new **Selected** folder inside that folder.

- **Nothing is uploaded.** It runs entirely in the browser, on your computer.
- **Originals are only read.** Nothing is moved, changed or deleted, and nothing in `Selected`
  is ever replaced. A file that is stopped or fails halfway is removed, so `Selected` never holds
  a half-copied photo, and each copy's size is checked against the original.
- **Same rules as the Mac and Windows copy scripts.** Every file in the photo's folder whose name
  starts with the photo's name and a dot is copied: the RAW, the JPEG, the `.xmp` sidecar. Sub-folders
  are kept. Upper and lower case are ignored when looking for files, and the copy uses the
  folder's real spelling.
- **Needs Chrome or Edge on a computer** (they let a page save into a folder you choose; Safari,
  Firefox and phones do not). The page says so when the browser cannot do it.

## Using it

1. On the event page, download **Spreadsheet (CSV)** (or **Plain list**).
2. Open the tool, choose that file (or drop it on the page).
3. Choose the same folder you uploaded from. The tool shows how many photos it found and how many
   files that is, and lists any it could not find.
4. Click **Copy**. The folder `Selected` appears inside your event folder.

"Try it with sample files" runs the whole thing on a pretend folder kept inside the browser's
private storage, so nobody has to risk real photos to see how it works.

## Running it

```bash
cd copy-tool
npm install
npm run dev        # http://localhost:5180
npm test           # 54 tests: CSV reading, matching, copying, and the screen
npm run build      # static files in dist/
```

`localhost` counts as a secure address, so the tool works there as it is. Anywhere else the page
must be served over **https**, or the browser will not allow folder access.

The built `dist/` folder is plain static files with relative paths: put it on any static host, in any
folder (for example `https://your-domain/copy/`). It never calls the PickSnap server.

## Layout

| File | What it does |
| --- | --- |
| `src/csv.ts` | Reads the CSV and the plain list; undoes the formula guard PickSnap adds to cells |
| `src/plan.ts` | Finds each photo's files in the folder before anything is copied |
| `src/copy.ts` | Copies with progress, stop, size check and clean-up; builds the problems list |
| `src/fs.ts` | The small slice of the folder API the tool uses, as interfaces |
| `src/demo.ts` | The sample folder and CSV |
| `src/App.tsx` | The three-step page |
