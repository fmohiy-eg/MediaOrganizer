# 📖 Media Organizer — User Guide

A friendly, plain-language guide to running and using your media organizer. No coding needed — just copy/paste the commands shown.

> **Which setup are you?** This guide walks through the **NAS + PC split** (scanning on a NAS over SSH, dashboard on a separate PC over SMB). If you're running everything on **one machine** (media on a local/external/mounted drive), you don't need the NAS/SSH/`path_map` steps — run `python setup_wizard.py`, then `python scan_live.py config.yaml`, then `python run_dashboard.py config.yaml`, all on the same computer. See **[README.md](README.md)** for the single-machine quick-start, then come back here for what each dashboard tab does (§4 onward). The audio-language tab and staging-folder names below are configurable (`audio_flag` in your config) and off until you enable them.

---

## 1. What this tool does

It looks at all the movies and TV shows on your NAS and helps you:

- 🔁 **Find duplicates** — the same movie/episode stored in several formats, so you can keep the best and reclaim space.
- 🧹 **Clean up old formats** — old `.rm`/`.wmv`/etc. files that already have a modern copy.
- 📺 **Spot missing episodes** — which already-aired episodes of your shows you don't have.
- 💬 **Get English subtitles** — download them, or check if a file already has built-in subs.
- 🏷️ **Fix mislabeled files** — rename and move a file that's in the wrong place / named wrong.
- ▶️ **Preview any file** — open it in VLC before you decide.

**Nothing is ever truly deleted.** "Delete" moves a file into a **quarantine** folder on the NAS that you can empty (or undo) yourself.

---

## 2. The two computers involved

| Where | Does what |
|-------|-----------|
| 🖥️ **The NAS** (`nas`) | Holds your media. The **scan** runs here (over SSH) because reading files locally is ~1000× faster than over the network. |
| 💻 **Your laptop** | Runs the **dashboard** (the web page you click around in) and talks to the internet (TMDB/TVDB/OpenSubtitles). |

The two share a small **catalog** (a database file) that lists everything found during a scan.

---

## 3. 🚀 Just want to look at your library? (everyday use)

If a scan has already been done, you only need the dashboard.

**On your laptop**, open **PowerShell** and run:

```powershell
cd C:\Users\user\MyImageApp\media_organize_app\Claude
python run_dashboard.py config.yaml
```

Then open your browser to **http://localhost:8080**.

To stop it later: click in that PowerShell window and press **Ctrl+C**.

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
- Buttons: **▶** plays the file in VLC, **Fix** relabels/moves it (see §5), **Delete** sends it to quarantine, **→ Arabic** moves just that file to `02-ArabicReady` (handy for a file you spot with an untagged Arabic track — see the Arabic Audio tab).
- **Navigation:** use **← Prev / Next →**, or type a number in the **Group _ of N** box and press Enter to jump straight to a group. The **type dropdown** (All / Movies / TV Shows) filters which duplicate groups you see. Opening a group also pre-fetches the next two in the background, so Next feels instant.
- The runtime/resolution/etc. fill in when you open a group; to pre-fill them for *all* groups (and enable the same/diff split), run the runtime probe — see §6 step **F**.

### Cleanup
A focused list of **old-format files that already have a modern copy** (e.g. 340 files / ~22 GB). Delete them one by one, or **"Quarantine all"** in one click. The modern copy keeps its shared subtitles/artwork automatically.

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
- **Delete** (on each file) — move just that file to quarantine (same as the Dupes tabs; nothing is erased, shared subtitles/NFO are preserved). Once removed, it drops off the list.
- Only the **movies** library is scanned; TV episodes are excluded (their filenames never match their `Season NN` folder). Case-only differences are ignored.

### Arabic Audio
Movies that have an **Arabic audio track** (detected from the probe data).
- **Move → 02-ArabicReady** — moves just the video file into a `02-ArabicReady`
  folder under your Movies share (keeping its `Title (Year)` folder name). It
  shows the exact From/To and asks you to confirm first; subtitles/NFO are left
  in the original folder. Nothing is deleted.
- The list fills in as `probe_dupes.py` finishes; a movie only appears once its
  audio has been probed.

### Needs Review
Files the tool couldn't identify (no Jellyfin info). Use **▶** to look, or **Fix** to identify and move them.

### Admin
Maintenance, all run from this PC (no SSH):
- **Catalog status** — rows, how many files are probed, unmatched count, episode-lists cached, a check that no stray backslash paths crept in, when the DB was last updated, and the running build.
- **OpenSubtitles quota** — once you've logged in on the Subtitles tab, shows downloads used / allowed / remaining today and when it resets.
- **Sync deletions** — click **Scan for deleted files**; it checks every catalogued file over the share and lists any whose file you deleted outside the app, then **Remove N row(s)** drops just those catalog rows (the DB is backed up first; no files are touched). This is the easy way to reconcile after deleting media in Explorer — no SSH or DB copy needed.
- **Quarantine** — **Scan quarantine** shows how many "deleted" files are parked and how much space (with the biggest ones listed); **Purge all** permanently frees that space (the only button that truly erases files — everything else is recoverable until you purge).
- **Enrichment jobs** — **Start probe** runs the runtime/audio probe in the background (resumable; powers the Duplicates split + Arabic Audio) with a **done / target / remaining progress bar**; if a few files won't probe it lists them (those are corrupt/unreadable — DVD `VIDEO_TS` fragments are skipped automatically). **Re-match unmatched** looks up the un-identified titles on TMDB/TVDB and tags the confident matches (it deliberately leaves ambiguous/junk names for manual Fix).
- **Database** — **Back up now** makes a timestamped snapshot under `_local\backups\`; **Integrity check** verifies the DB isn't corrupt.

### Organize Folder
Bulk-import a folder of loose TV files straight into the library, with a per-file and whole-folder decision.
1. Type or paste the **folder path** this PC can reach — a local folder (`D:/Downloads/NewShow`) or an SMB share (`//nas/Movies/01-Ready/Some Folder`). Click **Scan**.
2. The app reads each video's **embedded** show/season/episode tags, looks the series up on TVDB, and shows a **before → after** preview for every file (the new Jellyfin name + path), plus how many subtitles move with it and how many stray sidecars get cleared. **Nothing has moved yet.**
3. **Decide:** untick any file you want to leave behind, or use **Select all** to toggle the whole batch. The **Move selected (N)** button tracks your choices.
4. **Clean up leftovers** (checkbox, on by default): after the move, stray artwork/`.nfo`/`.trickplay` are sent to quarantine and the now-empty folder is removed — but only if you moved out **every** video (if you leave any file behind, the folder is kept intact).
5. Click **Move selected**. Each chosen video is renamed to Jellyfin format and moved into `TV Shows/01-Ready/Series (Year)/Season NN/…`; matching subtitles move alongside; everything removed goes to quarantine (recoverable, never erased). It never overwrites an existing file. If the source was already in the catalog (e.g. a misfiled folder under Movies), its catalog entry is repointed and its probe data carried over.

⚠️ **Important — it uses *embedded* tags, not the filename.** A file is matched only if the show/season/episode live *inside* the file's metadata — either structured tags or a composite `title` tag like `The West Wing S01E10 In Excelsis Deo`. Files with no usable embedded tags show as **"no embedded episode tags (skipped)"** and are left untouched. If most of your files get skipped, tell me and I'll add a filename-based fallback (you were offered this and chose embedded-only).

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

When your library changes, refresh the catalog. There are 5 short steps (2 on the NAS, 3 on the laptop).

### On the NAS (over SSH)

Open PowerShell on your laptop and connect:
```powershell
ssh admin@nas
```
(enter your NAS password). Then:

**A. Scan the library** (~4 minutes) — adds new files and updates changed ones:
```bash
cd /share/Public/media_organizer && /usr/local/bin/python3 -u scan_live.py config.yaml
```

**A2. Prune deleted files** — removes catalog rows for files no longer on disk (the removal half of a full sync). It previews first; re-run with `--apply` to commit:
```bash
/usr/local/bin/python3 -u prune_live.py config.yaml            # preview what would be removed
/usr/local/bin/python3 -u prune_live.py config.yaml --apply    # then actually remove them
```
(Skip this if you only added media. It only deletes DB rows, never files — re-running the scan re-adds anything pruned by mistake.)

**B. Read the Jellyfin IDs**:
```bash
/usr/local/bin/python3 -u read_nfo_ids.py config.yaml
```
Type `exit` to close the NAS connection.

### On your laptop (PowerShell)

**C. Copy the fresh catalog from the NAS:**
```powershell
Copy-Item '\\nas\Public\media_organizer\_data\media_audit.db' 'C:\Users\user\MyImageApp\media_organize_app\Claude\_local\media_audit.db' -Force
```

**D. Fetch each show's episode list** (for the Missing Episodes tab, ~15 min — only needed if you want missing-episode info):
```powershell
cd C:\Users\user\MyImageApp\media_organize_app\Claude
python gaps_live.py config.yaml
```

**E. Start the dashboard** (or restart it if it's already running):
```powershell
python run_dashboard.py config.yaml
```

**F. (Optional) Probe runtimes & audio** — fills in runtime/resolution/codec/audio for all duplicate copies *and* all movies, which powers the **Same length / Diff length** split (and the upcoming Arabic-audio feature). It's slow over the share (~hours) but **resumable** — re-running skips what's already done:
```powershell
python probe_dupes.py config.yaml
```

> 💡 You don't have to do all of these every time. Day-to-day, just **E**. After adding media, do **A → E**. Run **F** occasionally when you want the duplicate runtime split filled in.

---

## 7. 🛟 Safety & undo

- **Deleting = quarantine, not erasing.** Files move to `\\nas\Public\media_organizer\.quarantine` on the NAS.
- **To undo a delete:** open that quarantine folder in Windows Explorer and move the file back to where it came from (the folder structure inside quarantine mirrors the original).
- **To permanently free the space:** once you're sure, delete the contents of that quarantine folder yourself.
- **Previews and lists never change anything** — only the **Delete**, **Quarantine all**, **Fetch sub**, and **Confirm move** buttons do, and deletes/moves always show you what will happen first.

---

## 8. 🔧 Troubleshooting

| Problem | Fix |
|--------|-----|
| Dashboard won't open at localhost:8080 | Make sure the `python run_dashboard.py config.yaml` window is still running. If it closed, run it again. |
| "Not reachable" when playing/deleting | The NAS share isn't connected. Open `\\nas` in Explorer to reconnect, then retry. |
| Missing Episodes tab is empty | Run step **6.D** (`gaps_live.py`) once to fetch the episode lists. |
| Subtitle "Fetch" says quota done | You've hit OpenSubtitles' daily limit; it shows when it resets. Try again then. |
| Numbers look stale after a scan | You forgot step **6.C** (copy the catalog to the laptop) — the dashboard reads the laptop's copy. |
| Features/links/tabs look **broken or like an old version** after an update | The running server is almost always **stale** — `run_dashboard.py` loads the code once at startup, so editing/pulling files does **nothing** until you restart it. Close the `run_dashboard.py` window and run it again, then **hard-refresh** the browser (**Ctrl+Shift+R**). Confirm it took: the small **`build <date> <time> <commit>`** stamp next to the subtitle at the top of the page should show the time you just restarted — if it still shows an old time, the restart didn't take. If the build time is fresh and a feature *still* misbehaves, it's a code/render problem, not staleness — don't spin up a second server on another port (that just leaves two copies running and confuses which one you're looking at). |
| VLC doesn't open | The tool uses VLC at `C:\Program Files (x86)\VideoLAN\VLC`; if you moved it, reinstall VLC. |

---

## 9. 📍 Where things live

- **App on the NAS:** `/share/Public/media_organizer/` (scan scripts + a static `ffprobe`).
- **App on the laptop:** `C:\Users\user\MyImageApp\media_organize_app\Claude\`.
- **Catalog database:** on the NAS at `…/_data/media_audit.db`; the laptop uses a copy in `…\Claude\_local\media_audit.db`.
- **Quarantine (deleted files):** `\\nas\Public\media_organizer\.quarantine`.
- **Your API keys & settings:** the laptop's `config.yaml` (kept private, never shared or committed to git).

---

*That's everything. Start with §3 to look around, and §6 whenever your library changes.*
