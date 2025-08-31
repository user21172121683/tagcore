# ***tagcore***

A modular command-line toolkit for managing and maintaining a FLAC-based music collection.

## Quick start

See the [Wiki](https://github.com/user21172121683/tagcore/wiki) for full documentation.

### Requirements

This software depends on the following Python packages:

- `mutagen`
- `Pillow`
- `PyYAML`
- `musicbrainzngs`
- `protobuf`

Install them using:

    pip install -r requirements.txt

You’ll also need to install `ffmpeg` and `flac` binaries:

Windows (via winget):

    winget install Gyan.FFmpeg Xiph.FLAC

### Running

Run `main.py` to open the interactive main menu interface:

    python main.py

### Configuration

The `config.yaml` file contains a `General` section and individual sections for each module.

### Modules

Currently implemented modules include:

- `Rymporter`: Parses an exported HTML file of your RateYourMusic collection and tags FLAC files accordingly.
- `Rymfetcher`: A helper tool that opens your RateYourMusic collection in your browser so you can export it as an HTML file.
- `Boxxxer`: Exports an XML of your Mixxx library to be imported into Rekordbox.
- `Ogger`: Keeps a lossy OGG library in sync with your main FLAC collection.
- `Flagger`: Scans FLAC files in your collection for potential issues in metadata, audio integrity, and cover art.
- `ReCoder`: Re-encodes FLAC files to a new compression level.
- `Stamper`: Applies static metadata tags to FLAC files.

In the pipeline:

- `ReBrainer`: Checks if files with MusicBrainz IDs can be updated with fresh metadata via the MusicBrainz API.
- `ReGainer`: Analyses and applies ReplayGain to FLAC files.
- `ReNamer`: Renames FLAC files according to a hard-coded scheme.

---

**Note:** Work in progress. Things might break, change, or just not work yet. Use at your own risk.
