# ***tagcore***

A modular command-line toolkit for managing and maintaining a FLAC-based music collection.

## Table of Contents

- [Requirements](#requirements)
- [Running](#running)
- [Configuration](#configuration)
- [Modules](#modules)
  - [Rymporter](#rymporter)
  - [Rymfetcher](#rymfetcher)
  - [Flagger](#flagger)
  - [Ogger](#ogger)
  - [ReBrainer](#rebrainer)
  - [ReCoder](#recoder)
  - [ReGainer](#regainer)
  - [ReNamer](#renamer)
  - [Stamper](#stamper)
- [TODO](#todo)
- [Adding your own modules](#adding-your-own-modules)

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

The `config.yaml` file contains a `General` section and individual sections for each module. Settings in the `General` section apply to all modules by default, but can be overridden in each module’s own section.

    General:
      dry_run: true
      main_dir: flac
      username: myusername
      console_level: INFO
      file_level: DEBUG

    Rymporter:
      collection_html_file: collection.html
      auto_skip: true
      field_definitions:
        album_id: RYM_ALBUMID
      fields_to_modify:
        RYM_ALBUMID: true

You can override any value in `config.yaml` directly from the command line using the `--override` argument **after** any modules when running `main.py`. Supports automatic type conversion for strings, numbers, booleans, lists, and dictionaries where valid Python literals are provided. This means that if your strings include spaces or special shell characters, you should wrap them in quotes to ensure they are parsed correctly by the shell and the application.

    --override Section.key.subkey=value

- `Section` is the section in your config file (e.g., `General` or any module name).
- `key.subkey` represents nested keys within that section.
- `value` is the new value you want to apply.

Example:

    python main.py rymporter flagger --override General.dry_run=true Rymporter.field_definitions.album_id=RYM_ALBUMID Flagger.tags_to_check=['GENRE','RYM_ALBUMID']

**Global configurable parameters:**

- `dry_run`: If `true`, simulates changes without modifying files.
- `main_dir`: The root directory of your main FLAC collection.
- `username`: Your RateYourMusic and MusicBrainz username (if the same).
- `console_level`: Log level for terminal output. Options: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.
- `file_level`: Log level for `.log` files (same options as above).

## Modules

### Rymporter

Parses an exported HTML file of your RateYourMusic collection and tags FLAC files accordingly. This is meant to be a hold-over while we wait for a proper API from RYM/Sonemic, meaning we are at the mercy of their spaghetti code.

Example output of [The Aftermath](https://rateyourmusic.com/release/ep/dystopia/the-aftermath/):

    {
        'album': {'album_id': '[Album1836208]', 'album_title': 'The Aftermath'},
        'artist': [
            {'artist_id': '[Artist39650]', 'artist_name': 'Dystopia'}
        ],
        'date': '1999',
        'genre': [
            {'genre_id': '[Genre437]', 'genre_name': 'Sludge Metal'},
            {'genre_id': '[Genre335]', 'genre_name': 'Crust Punk'}
        ],
        'label': {'label_id': '[Label4124]', 'label_name': 'Life Is Abuse'},
        'ownership': 'Digital',
        'rating': '5.0',
        'tag': []
    }

**Note:** Catalog numbers and artist collaborative names are currently broken.

**Configuration:**

- `collection_html_file`: Name to the saved HTML file (placed in `data/`).
- `auto_skip`: If `true`, skips albums that can’t be auto-matched. If `false`, prompts for a manual RYM ID in format `[Album123]`. If none provided, it will still skip the album.
- `field_definitions`: Maps RYM data to FLAC tag fields. Must include either `album_id`, or both `album_title` and `album_artist`, otherwise files can't be matched.
- `fields_to_modify`: Dictates which fields are allowed to be modified (`true` or `false`).

### Rymfetcher

A helper tool that opens your RateYourMusic collection in your browser so you can export it as an HTML file. Use the exported HTML file with `Rymporter` to tag your FLAC files.

**Usage:**

- When run, it will open the appropriate URL for your RYM collection in your default browser.
- You must be **logged into RateYourMusic** with the specified username for it to load correctly.
- After opening the page, save it as an .html file in the `data/` directory.
- Update the `collection_html_file` value in your config to point to the saved file.

**Configuration:**

- `username`: Your RateYourMusic username. If not provided, you’ll be prompted to enter it when running the module.

### Flagger

Scans FLAC files in your collection for potential issues in metadata, audio integrity, and cover art. It then flags problems in a designated Vorbis comment field.

**Cover art checks performed:**

- Ensures only one image is embedded. If multiple are found, only the first is analysed.
- Checks if the image is square.
- Checks if the image is bigger or smaller than target size.

**Configuration:**

- `problems_field`: The Vorbis comment field where detected issues are recorded (e.g., `PROBLEMS`).
- `timestamp`: If `true`, adds a `{problems_field}_LASTCHECKED` tag with the current date.
- `skip_integrity_check`: Set to `false` to run full FLAC stream integrity verification (slow but thorough). Set to `true` to skip it for faster scans.
- `tags_to_check`: A list of expected tags to verify. Missing or empty tags will be reported as `NO {tag}`.
- `cover_target_size`: A list (e.g., `[600, 600]`) for expected cover art dimensions. Converted to a tuple at runtime.
- `cover_allowed_formats`: List of allowed image formats (e.g., `['jpeg', 'png']`).

### Ogger

Keeps a lossy OGG library in sync with your main FLAC collection. Updates files if metadata doesn't match, but also if OGG stream doesn't match config.

It matches files based on:

1. A track ID field (e.g. `MUSICBRAINZ_RELEASETRACKID`)
2. A generated metadata fingerprint
3. File path (optional, can be disabled)

**Configuration:**

- `ogg_dir`: Path to the lossy OGG collection.
- `track_id_field`: Unique identifier tag used for matching.
- `filename_match`: If `true`, tries file path as a fallback.
- `fields_to_preserve`: List of tags to preserve. Use `"*"` to preserve all.
- `quality`: OGG VBR quality (0–10).
- `sample_rate`: Output sample rate in Hz.
- `channels`: `1` for mono, `2` for stereo.

### ReBrainer

Checks if files with MusicBrainz IDs can be updated with fresh metadata via the MusicBrainz API. **NOT IMPLEMENTED**

### ReCoder

Re-encodes FLAC files to a new compression level. Optionally records the level in metadata.

**Configuration:**

- `level`: The FLAC compression level (0-8).
- `stamp`: The Vorbis comment field to record the encoding level (e.g., `ENCODE_LEVEL`). This is also used to skip unnecessary processing.

### ReGainer

Analyses and applies ReplayGain to FLAC files. **NOT IMPLEMENTED**

### ReNamer

Renames FLAC files according to a hard-coded scheme. **NOT IMPLEMENTED**

### Stamper

Applies static metadata tags to FLAC files. Overwrites the fields if necessary, does not append.

**Configuration:**

- `stamps`: A simple mapping of key-value pairs to be applied to every file. Set value to be a list to map multiple values. Set value to an empty list (`[]`) to delete the tag.

## TODO

1. ReBrainer:
    - Implement the whole thing.
2. ReGainer:
    - Implement the whole thing.
3. ReNamer:
    - Implement the whole thing.
4. Flagger:
    - Add toggles to enable/disable:
        - Squareness check
        - Multiple images check
5. Ogger:
    - Add support for cover art.
6. Rymporter:
    - Combine `field_definitions` and `fields_to_modify` into one object.
    - Add toggle for artist-title matching.
    - Fix catalog number parsing.
    - Fix artist collab name parsing.
7. General:
    - Stricter typing
    - Make clearer what is optional

## Adding your own modules

To add a module, create a `.py` file in `src/modules/`. Include a `.run()` method—this makes the module discoverable. To configure it in `config.yaml`, just create new section for it with the name of the class (case-sensitive.) The configuration is passed to the class upon runtime as kwargs, along with what is configured in `General`.

---

**Note:** Work in progress. Things might break, change, or just not exist yet. Use at your own risk.
