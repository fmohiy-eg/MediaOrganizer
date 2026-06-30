# 📖 Media Organizer — User Guide

A friendly, plain-language guide to running and using the media organizer. No coding needed — just copy/paste the commands shown.

> **Two ways to run it.** **Single machine** (simplest): your media is on a local, external, or mounted drive and everything runs on one computer — see **[README.md](README.md)** for the quick-start, then use §4 below for what each dashboard tab does. **NAS + PC split** (advanced): the scan runs on a NAS over SSH and the dashboard runs on a separate PC over the network — §2, §3 and §6 cover that. Throughout, replace placeholders like `<nas-ip>` and `path\to\MediaOrganizer` with your own values.
>
> The **Audio Language** tab and the staging-folder names are **optional and configurable** (`audio_flag` in your config) — off until you enable them.

---

## 1. What this tool does

It looks at all the movies and TV shows in your library and helps you:

- 🔁 **Find duplicates** — the same movie/episode stored in several formats, so you can keep the best and reclaim space.
- 🧹 **Clean up old formats** — old `.rm`/`.wmv`/etc. files that already have a modern copy.
- 📺 **Spot missing episodes** — which already-aired episodes of your shows you don't have.
- 💬 **Get English subtitles** — download them, or check if a file already has built-in subs.
- 🏷️ **Fix mislabeled files** — rename and move a file that's in the wrong place / named wrong.
- ▶️ **Preview any file** — open it in your media player before you decide.

**Nothing is ever truly deleted.** "Delete" moves a file into a **quarantine** folder that you can empty (or undo) yourself.

---

## 2. Running on one machine vs a NAS + PC split

- **Single machine** — media on a local/mounted drive; the scan and the dashboard run on the same computer. No SSH, no network paths. See README for setup, then jump to §4.
- **NAS + PC split** — the **scan** runs on the NAS (over SSH) because reading files locally is ~1000× faster than over the network; the **dashboard** runs on your PC (it talks to the internet for TMDB/TVDB/OpenSubtitles). The two share a small **catalog** (a database file) that lists everything found during a scan, and a `path_map` in your config translates the NAS paths to network paths for the PC.

The rest of this guide uses the term "the project folder" for wherever you installed the app (e.g. the folder you cloned from GitHub).

---

## 3. 🚀 Just want to look at your library? (everyday use)

If a scan has already been done, you only need the dashboard. Open a terminal **in the project folder** and run:

```bash
cd path\to\MediaOrganizer
python run_dashboard.py config.yaml
```

Then open your browser to **http://localhost:8080**. To stop it later: click in that terminal window and press **Ctrl+C**.

---

## 4. 🗂️ The dashboard, tab by tab

### Overview
The big picture: total items, storage used, how many duplicate groups / missing-subtitle files / items needing review.

### Dupes · Same length  /  Dupes · Diff length
Duplicate groups are split into **two tabs by runtime**:
- **Same length** — every copy has the same runtime → genuine duplicates, safe to dedupe.
- **Diff length** — at least one copy differs (or hasn't been runtime-checked yet) → review carefully; they might be *different versions* (a cut-down file, a Director's Cut, etc.).

Each steps through groups **one at a time** (biggest space-savings first) and shows, per copy: **runtime, resolution, codec, embedded subtitles, the file's internal title, and size**, with a suggested **KEEP?** (just a hint — you can delete **any** copy, including the suggested one).
- A **red note** under a filename means its **internal title disagrees with the filename** — a sign the file is mislabeled.
- Buttons: **▶** plays the file, **Fix** relabels/moves it (see §5), **Delete** sends it to quarantine. If you've enabled the **Audio Language** feature, a button also appears to move just that file into your configured staging folder.
- **Navigation:** use **← Prev / Next →**, or type a number in the **Group _ of N** box and press Enter to jump straight to a group. The **type dropdown** (All / Movies / TV Shows) filters which duplicate groups you see. Opening a group also pre-fetches the next two in the background, so Next feels instant.
- The runtime/resolution/etc. fill in when you open a group; to pre-fill them for *all* groups (and enable the same/diff split), run the runtime probe — see §6 step **F**.

### Cleanup
A focused list of **old-format files that already have a modern copy**. Delete them one by one, or **"Quarantine all"** in one click. The modern copy keeps its shared subtitles/artwork automatically.

### Missing Episodes
For each show, the episodes that **already aired but aren't on your disk** (e.g. *Adventure Time — missing S07E15, S08E13*). Future episodes and "Specials" are not counted.
*(Needs the episode lists fetched first — see §6 step D.)*

### Subtitles
Files with **no external English subtitle**.
- **Log in** to OpenSubtitles (top of the tab) — your login is kept only while the page is open, never saved.
- **Check built-in** — see if a file already has an English subtitle baked in (so you don't waste a download).
- **Fetch sub** — downloads the best English subtitle, unzips/cleans it, and drops it next to the video.
- The **quota** indicator shows how many downloads you have left today and when it resets (free accounts get a limited number per day).

### Mismatch Videos
Movie folders containing a video file whose name **doesn't match the folder name** — e.g. a `… - CD1`/`CD2` part, a scene-named file (`28.Days.Later.2002.720p…`), or a stray episode/sample dropped in the wrong folder. Grouped by folder so you can work through them one at a time.
- **Fix** (on each file) — identify it as the correct movie or TV show, then rename/relocate it to the right place (same flow as the Fix button elsewhere). Once fixed, it drops off the list.
- **Delete** (on each file) — move just that file to quarantine (nothing is erased, shared subtitles/NFO are preserved). Once removed, it drops off the list.
- Only the **movies** library is scanned; TV episodes are excluded (their filenames never match their `Season NN` folder). Case-only differences are ignored.

### Audio Language *(optional — appears only when enabled)*
Movies that have an audio track in the language(s) you configured (`audio_flag.languages`, e.g. `["ara"]` for Arabic, `["spa"]` for Spanish), detected from the probe data. The tab's name is whatever you set as `audio_flag.label`.
- **Move** — relocates just the video file into your configured staging subfolder (`audio_flag.staging_subdir`) under your Movies root, keeping its `Title (Year)` folder name. It shows the exact From/To and asks you to confirm first; subtitles/NFO are left in the original folder. Nothing is deleted.
- The list fills in as the probe (`probe_dupes.py`) finishes; a movie only appears once its audio has been probed.
- If you haven't set `audio_flag.languages`, this tab is hidden entirely.

### Needs Review
Files the tool couldn't identify (no Jellyfin info). Use **▶** to look, or **Fix** to identify and move them.

### Admin
Maintenance, all run from the machine hosting the dashboard (no SSH):
- **Catalog status** — rows, how many files are probed, unmatched count, episode-lists cached, a path-style sanity check, when the DB was last updated, and the running build.
- **OpenSubtitles quota** — once you've logged in on the Subtitles tab, shows downloads used / allowed / remaining today and when it resets.
- **Sync deletions** — click **Scan for deleted files**; it checks every catalogued file and lists any whose file you deleted outside the app, then **Remove N row(s)** drops just those catalog rows (the DB is backed up first; no files are touched). The easy way to reconcile after deleting media in your file manager.
- **Quarantine** — **Scan quarantine** shows how many "deleted" files are parked and how much space (with the biggest ones listed); **Purge all** permanently frees that space (the only button that truly erases files — everything else is recoverable until you purge).
- **Enrichment jobs** — **Start probe** runs the runtime/audio probe in the background (resumable; powers the Duplicates split + the Audio Language feature) with a **done / target / remaining progress bar**; if a few files won't probe it lists them (those are corrupt/unreadable — DVD `VIDEO_TS` fragments are skipped automatically). **Re-match unmatched** looks up un-identified titles on TMDB/TVDB and tags the confident matches (it deliberately leaves ambiguous/junk names for manual Fix).
- **Database** — **Back up now** makes a timestamped snapshot; **Integrity check** verifies the DB isn't corrupt.

### Organize Folder
Bulk-import a folder of loose TV files straight into the library, with a per-file and whole-folder decision.
1. Type or paste a **folder path** this machine can reach — a local folder (`D:/Downloads/NewShow`) or a network share. Click **Scan**.
2. The app reads each video's **embedded** show/season/episode tags, looks the series up on TVDB, and shows a **before → after** preview for every file (the new Jellyfin name + path), plus how many subtitles move with it and how many stray sidecars get cleared. **Nothing has moved yet.**
3. **Decide:** untick any file you want to leave behind, or use **Select all** to toggle the whole batch. The **Move selected (N)** button tracks your choices.
4. **Clean up leftovers** (checkbox, on by default): after the move, stray artwork/`.nfo`/`.trickplay` are sent to quarantine and the now-empty folder is removed — but only if you moved out **every** video (if you leave any file behind, the folder is kept intact).
5. Click **Move selected**. Each chosen video is renamed to Jellyfin format and moved into your TV library (`Series (Year)/Season NN/…`); matching subtitles move alongside; everything removed goes to quarantine (recoverable, never erased). It never overwrites an existing file. If the source was already in the catalog, its entry is repointed and its probe data carried over.

⚠️ **Important — it uses *embedded* tags, not the filename.** A file is matched only if the show/season/episode live *inside* the file's metadata — either structured tags or a composite `title` tag like `The West Wing S01E10 In Excelsis Deo`. Files with no usable embedded tags show as **"no embedded episode tags (skipped)"** and are left untouched.

---

## 5. 🏷️ Fixing a mislabeled or misplaced file ("Fix" button)

When a file is the wrong movie/show or in the wrong folder:

1. Click **Fix** (on the Duplicates or Needs Review tab).
2. Choose **Movie** or **TV Episode**.
3. Type the **correct title** (for TV, also enter the **Season** and **Episode** numbers) and click **Look up**.
4. Pick the right match from the list (title + year, from TMDB/TVDB).
5. Check the **preview** — it shows where the file will move to (proper Jellyfin name + folder).
6. Click **Confirm move**.

It creates the correct folder if needed and moves just that one file there. It won't overwrite an existing file.

---

## 6. 🔄 Refreshing after you add or remove media

When your library changes, refresh the catalog.

### Single machine

Everything runs in one place:

```bash
cd path\to\MediaOrganizer
python scan_live.py config.yaml        # add new files / update changed ones
python run_dashboard.py config.yaml    # (re)start the dashboard
```

Optionally `python read_nfo_ids.py config.yaml` (pull IDs from Jellyfin `.nfo` files), `python gaps_live.py config.yaml` (episode lists for the Missing Episodes tab), and `python probe_dupes.py config.yaml` (runtimes/audio for the Duplicates split + Audio Language). To remove catalog rows for files you deleted on disk, use the Admin **Sync deletions** panel.

### NAS + PC split

Two steps on the NAS, three on the PC. Replace `<nas-ip>`, `<nas-user>` and the NAS app path with yours.

**On the NAS (over SSH).** From a terminal on your PC:
```bash
ssh <nas-user>@<nas-ip>
```
Then:

**A. Scan the library** — adds new files and updates changed ones:
```bash
cd <app-folder-on-nas> && python3 -u scan_live.py config.yaml
```

**A2. Prune deleted files** *(skip if you only added media)* — removes catalog rows for files no longer on disk. Previews first; re-run with `--apply` to commit:
```bash
python3 -u prune_live.py config.yaml            # preview
python3 -u prune_live.py config.yaml --apply    # then remove
```

**B. Read the Jellyfin IDs**, then `exit` to close the connection:
```bash
python3 -u read_nfo_ids.py config.yaml
```

**On your PC.**

**C. Copy the fresh catalog from the NAS** to wherever your PC `config.yaml` expects the database (the `database_path` value).

**D. Fetch each show's episode list** (for Missing Episodes — only if you want that info):
```bash
cd path\to\MediaOrganizer
python gaps_live.py config.yaml
```

**E. Start (or restart) the dashboard:**
```bash
python run_dashboard.py config.yaml
```

**F. (Optional) Probe runtimes & audio** — fills in runtime/resolution/codec/audio for all duplicate copies and all movies, powering the **Same length / Diff length** split (and the Audio Language feature). Slow over the network but **resumable**:
```bash
python probe_dupes.py config.yaml
```

> 💡 You don't have to do all of these every time. Day-to-day, just **E**. After adding media, do **A → E**. Run **F** occasionally when you want the duplicate runtime split filled in.

---

## 7. 🛟 Safety & undo

- **Deleting = quarantine, not erasing.** Files move to the quarantine folder set in your config (`quarantine_path`).
- **To undo a delete:** open that quarantine folder in your file manager and move the file back to where it came from (the folder structure inside quarantine mirrors the original).
- **To permanently free the space:** once you're sure, use Admin → **Purge all** (or delete the quarantine folder's contents yourself).
- **Previews and lists never change anything** — only the **Delete**, **Quarantine all**, **Fetch sub**, and **Confirm move** buttons do, and deletes/moves always show you what will happen first.

---

## 8. 🔧 Troubleshooting

| Problem | Fix |
|--------|-----|
| Dashboard won't open at localhost:8080 | Make sure the `python run_dashboard.py config.yaml` window is still running. If it closed, run it again. |
| Runtime/codec/audio columns or the Probe panel don't work | `ffprobe` isn't installed or found. See README → Prerequisites. The dashboard prints a warning at startup if it's missing; set `ffprobe.binary` in config if it's installed somewhere unusual. |
| "Not reachable" when playing/deleting (NAS split) | The network share isn't connected. Reconnect it in your file manager, then retry. |
| Missing Episodes tab is empty | Run step **6.D** (`gaps_live.py`) once to fetch the episode lists. |
| Subtitle "Fetch" says quota done | You've hit OpenSubtitles' daily limit; it shows when it resets. Try again then. |
| Numbers look stale after a scan (NAS split) | You forgot step **6.C** (copy the catalog to the PC) — the dashboard reads the PC's copy. |
| Features/links/tabs look **broken or like an old version** after an update | The running server is almost always **stale** — `run_dashboard.py` loads the code once at startup, so editing/pulling files does **nothing** until you restart it. Close the window and run it again, then **hard-refresh** the browser (**Ctrl+Shift+R**). Confirm it took: the **`build <date> <time> <commit>`** stamp at the top of the page should show the time you just restarted. Don't spin up a second server on another port — that just leaves two copies running. |
| Play button doesn't open anything | The app auto-detects VLC, else opens the OS default player. Install VLC, or set `player.binary` in config to your player's path. |

---

## 9. 📍 Where things live

Everything is driven by your `config.yaml`:

- **The app:** the project folder you installed it into.
- **Catalog database:** the `database_path` in your config.
- **Quarantine (deleted files):** the `quarantine_path` in your config.
- **Your API keys & settings:** `config.yaml` (and an optional `.env`) — kept private, never committed to git.

---

*That's everything. Start with §3 to look around, and §6 whenever your library changes.*
