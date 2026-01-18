# identify_audio (kaiano)

Local-filesystem **audio identification**, **tagging**, and **renaming** utilities wrapped behind a clean, reusable interface.

This module is intentionally **Drive-agnostic**: it only works with local file paths. If you’re working with Google Drive, your Drive middleware should download to a temp path, call this module on the temp file, then upload/update the Drive file.

---

## What it does

### 1) Identify (AcoustID → candidates)
Uses Chromaprint/`fpcalc` via the `acoustid` library to generate an audio fingerprint and query AcoustID, returning candidate recordings with confidence scores.

### 2) Metadata (MusicBrainz)
Fetches richer track metadata from MusicBrainz for a chosen candidate.

### 3) Tags (music-tag + VirtualDJ compatibility)
Reads and writes audio tags (ID3/MP4/etc) using `music_tag` with optional VirtualDJ-friendly output behavior.

### 4) Rename (local only)
Proposes and applies safe local filenames based on metadata (e.g. `{title}_{artist}.mp3`).

### 5) Optional “pipeline” convenience
A convenience wrapper that composes identify/tag/rename, but **each step is still usable independently**.

---

## Public entry point

Most code should only import **AudioToolbox**:

```python
from kaiano.library.identify_audio import AudioToolbox
```

Advanced use (lower-level orchestrator):

```python
from kaiano.library.identify_audio import IdentifyAudio
```

---

## Quick start

```python
from kaiano.library.identify_audio import AudioToolbox

tool = AudioToolbox.from_env(acoustid_api_key="YOUR_ACOUSTID_KEY")

result = tool.pipeline.process_file(
    "/path/to/song.mp3",
    do_identify=True,
    do_tag=True,
    do_rename=True,
    min_confidence=0.90,
)

print(result.identified, result.reason, result.path_out, result.desired_filename)
```

---

## Usage patterns

### A) Identify only (no tagging, no rename)

```python
from kaiano.library.identify_audio import AudioToolbox

tool = AudioToolbox.from_env(acoustid_api_key="YOUR_ACOUSTID_KEY")

snapshot = tool.tags.read("/path/to/song.mp3")  # optional but recommended
candidates = tool.identify.candidates("/path/to/song.mp3", snapshot)

best = max(candidates, key=lambda c: c.confidence) if candidates else None
print(best)
```

### B) Fetch metadata only (given a candidate)

```python
meta = tool.metadata.fetch(best)
print(meta.title, meta.artist, meta.year)
```

### C) Tagging only (rewrite tags without identification)

This is useful for VirtualDJ compatibility fixes.

```python
from kaiano.library.identify_audio import AudioToolbox, TagPolicy

tool = AudioToolbox.from_env(acoustid_api_key="YOUR_ACOUSTID_KEY")

snapshot = tool.tags.read("/path/to/song.mp3")
updates = tool.pipeline._passthrough_updates_from_snapshot(snapshot)  # internal helper used by pipeline
tool.tags.write("/path/to/song.mp3", updates, ensure_virtualdj_compat=True)
```

> If you don’t want to reach into internal helpers, use the pipeline with `do_identify=False`:
>
> ```python
> result = tool.pipeline.process_file(
>     "/path/to/song.mp3",
>     do_identify=False,
>     do_tag=True,
>     do_rename=False,
> )
> ```

### D) Rename only (local)

```python
from kaiano.library.identify_audio import AudioToolbox

tool = AudioToolbox.from_env(acoustid_api_key="YOUR_ACOUSTID_KEY")

snapshot = tool.tags.read("/path/to/song.mp3")
# Build a rename using whatever metadata you have
proposal = tool.rename.propose(
    "/path/to/song.mp3",
    title=snapshot.tags.get("tracktitle"),
    artist=snapshot.tags.get("artist"),
    template="{title}_{artist}",
)
new_path = tool.rename.apply(proposal.src_path, type("U", (), {"title": proposal.dest_name, "artist": ""})())  # or use pipeline
print(new_path)
```

> In practice, renaming is easiest via the pipeline because it already has access to the metadata used for tagging.

---

## Pipeline behavior

`AudioToolbox.pipeline.process_file(...)` does:

1. Reads tags (when needed)
2. Identifies via AcoustID (optional)
3. If no candidates / low confidence / identify disabled:
   - optionally rewrites existing tags (`TagPolicy.on_identify_fail == "passthrough"`)
   - optionally renames (only if title+artist available, unless configured otherwise)
4. If confident match:
   - fetches metadata from MusicBrainz
   - writes tags
   - optionally renames

Returned object: `PipelineResult`

Fields you’ll likely use in middleware:
- `identified`: bool
- `reason`: `"ok" | "no_candidates" | "low_confidence" | "identify_disabled"`
- `path_out`: final local path (may be same as input)
- `desired_filename`: basename of output file
- `wrote_tags`: bool
- `renamed`: bool

---

## Policies

### IdentificationPolicy
Controls identification thresholds and candidate count.

```python
from kaiano.library.identify_audio import IdentificationPolicy

policy = IdentificationPolicy(min_confidence=0.90, max_candidates=5)
```

### TagPolicy
Controls how tagging behaves on identify failures.

- `ensure_virtualdj_compat`: rewrite tags in a VirtualDJ-friendly way (recommended for MP3)
- `on_identify_fail`:
  - `"passthrough"`: rewrite existing readable tags
  - `"skip"`: do nothing

```python
from kaiano.library.identify_audio import TagPolicy

tag = TagPolicy.virtualdj_safe()
```

### RenamePolicy
Controls rename behavior:
- `enabled`
- `template`
- `require_title_and_artist`

```python
from kaiano.library.identify_audio import RenamePolicy

rename = RenamePolicy.template_policy("{title}_{artist}", require_title_and_artist=True)
```

---

## Troubleshooting

### AcoustID FingerprintGenerationError: “audio could not be decoded”
This happens when Chromaprint/`fpcalc` can’t decode the audio stream (corrupt file, wrong extension, missing codecs in runtime).

Fix options:
- Re-encode the file: `ffmpeg -i in.mp3 -q:a 2 out.mp3`
- Convert to WAV for fingerprinting
- Treat it as “no_candidates” and rely on passthrough tagging

### “Method not found” errors (e.g. dump vs dump_tags)
This usually means the underlying implementation changed names. The facades in this module are intended to smooth that over. If you see these errors, update `kaiano` in the consuming project to ensure you’re running the latest version.

---

## Drive middleware (recommended pattern)

This module is local-only. For Google Drive workflows:

1. Download Drive file → temp path
2. Run `tool.pipeline.process_file(temp_path, ...)`
3. If not identified (or low confidence): update the Drive file in place (same file ID)
4. If identified: upload to destination + delete source

---

## Notes

- The zip you uploaded included a `__MACOSX/` folder. That folder is safe to delete and should not be committed.

