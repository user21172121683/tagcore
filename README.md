# ***tagcore***

A modular command-line toolkit for managing and maintaining a FLAC-based music collection.

## Requirements

This software depends on the following Python packages:

- `mutagen`
- `Pillow`
- `PyYAML`
- `musicbrainzngs`

Install them using:

    pip install -r requirements.txt

You’ll also need to install `ffmpeg` and `flac` binaries:

Windows (via winget):

    winget install Gyan.FFmpeg Xiph.FLAC

## Running

Run `main.py` to open the main menu interface. You can also provide module names as command-line arguments to automatically run them in sequence (case-insensitive):

    python main.py rymporter rebrainer flagger ogger

## Configuration

The `config.yaml` file contains a `General` section and individual sections for each module.

Settings in `General` are shared across all modules but can be overridden in their respective sections.

### Global Configurable Parameters

- `dry_run`: If `true`, simulates changes without modifying files.
- `main_dir`: The root directory of your main FLAC collection.
- `username`: Your RateYourMusic and MusicBrainz username (if the same).
- `console_level`: Log level for terminal output. Options: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.
- `file_level`: Log level for `.log` files (same options as above).

## The modules

### Rymporter

Parses an exported HTML file of your RateYourMusic collection and tags FLAC files accordingly.

**Configurable Parameters:**

- `collection_html_file`: Path to the saved HTML file (placed in `data/`).
- `auto_skip`: If `true`, skips albums that can’t be auto-matched. If `false`, prompts for a manual RYM ID in format `[Album123]`. If none provided, it will still skip the album.
- `field_definitions`: Maps RYM data to FLAC tag fields. Must include either `album_id`, or both `album_title` and `album_artist`, otherwise files can't be matched.
- `fields_to_modify`: Dictates which fields are allowed to be modified (`true` or `false`).

**TODO:**

- Add toggle for artist-title matching.
- Combine `field_definitions` and `fields_to_modify` into one mapping.

### Rymfetcher

A helper tool that opens your RateYourMusic collection in your browser so you can export it as an HTML file. This file can then be used by `Rymporter` for tagging your FLAC files.

**Usage:**

- When run, it will open the appropriate URL for your RYM collection in your default browser.
- You must be **logged into RateYourMusic** with the specified username for it to load correctly.
- Once open, save the page as an `.html` file and place it in the `data/` directory.
- Update the `collection_html_file` value in your config to point to the saved file.

**Configuration:**

- `username`: Your RateYourMusic username. If not provided, you’ll be prompted to enter it when running the module.

### Flagger

Scans FLAC files in your collection for potential issues in metadata, audio integrity, and cover art. It then flags problems in a designated Vorbis comment field.

**Configurable Parameters:**

- `problems_field`: The Vorbis comment field where detected issues are recorded (e.g., `PROBLEMS`).
- `timestamp`: If `true`, adds a `{problems_field}_LASTCHECKED` tag with the current date.
- `skip_integrity_check`: Set to `false` to run full FLAC stream integrity verification (slow but thorough). Set to `true` to skip it for faster scans.
- `tags_to_check`: A list of expected tags to verify. Missing or empty tags will be reported as `NO {tag}`.
- `cover_target_size`: A list (e.g., `[600, 600]`) for expected cover art dimensions. Converted to a tuple at runtime.
- `cover_allowed_formats`: List of allowed image formats (e.g., `['jpeg', 'png']`).

**Cover Art Checks Performed:**

- Ensures only one image is embedded. If multiple are found, only the first is analysed.
- Checks if the image is square.
- Checks if the image is bigger or smaller than target size.

**TODO:**

- Add toggles to enable/disable:
  - Squareness check
  - Multiple images check

### Ogger

Keeps a lossy OGG library in sync with your main FLAC collection.

It matches files based on:

1. A track ID field (e.g. `MUSICBRAINZ_RELEASETRACKID`)
2. A generated metadata fingerprint
3. File path (optional, can be disabled)

**Configurable Parameters:**

- `ogg_dir`: Path to the lossy OGG collection.
- `track_id_field`: Unique identifier tag used for matching.
- `filename_match`: If `true`, tries file path as a fallback.
- `fields_to_preserve`: List of tags to preserve. Use `"*"` to preserve all.
- `quality`: OGG VBR quality (0–10).
- `sample_rate`: Output sample rate in Hz.
- `channels`: `1` for mono, `2` for stereo.

**TODO:**

- Add support for cover art.

### ReBrainer

Checks if files with MusicBrainz IDs can be updated with fresh metadata via the MusicBrainz API.

**TODO:**

- Implement the whole thing.

### ReCoder

Re-encodes FLAC files to a new compression level.

**Configurable Parameters:**

- `level`: The FLAC compression level (0-8).
- `stamp`: The Vorbis comment field to record the encoding level (e.g., `ENCODE_LEVEL`). This is also used to skip unnecessary processing.

### ReGainer

Analyses and applies ReplayGain to FLAC files.

**TODO:**

- Implement the whole thing.

### ReNamer

Renames FLAC files according to a hard-coded scheme.

**TODO:**

- Implement the whole thing.

---

**Note:** Work in progress. Things might break, change, or just not exist yet. Use at your own risk.
