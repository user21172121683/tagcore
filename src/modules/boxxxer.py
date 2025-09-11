import sqlite3
import time
import xml.etree.ElementTree as ET
from statistics import mean
import logging
import threading
from pathlib import Path
from google.protobuf.message import DecodeError

from modules import _beats_pb2
from utils import get_config, DATA_DIR, check_stop, summary_message, dry_run_message


class Boxxxer:
    """Exports an XML of your Mixxx library to be imported into Rekordbox."""

    _MIXXX_DB_INCLUDE = [
        "PlaylistTracks",
        "Playlists",
        "crate_tracks",
        "crates",
        "cues",
        "library",
        "track_locations",
    ]

    _TRACK_MAP = {
        "TrackID": "id",
        "Name": "title",
        "Artist": "artist",
        "Composer": "composer",
        "Album": "album",
        "Grouping": "grouping",
        "Genre": "genre",
        "Kind": "filetype",
        "Size": "filesize",
        "TotalTime": "duration",
        "DiscNumber": "discnumber",  # Not stored by Mixxx, set to 0
        "TrackNumber": "tracknumber",
        "Year": "year",
        "AverageBpm": "bpm",
        "DateAdded": "datetime_added",
        "BitRate": "bitrate",
        "SampleRate": "samplerate",
        "Comments": "comment",
        "PlayCount": "timesplayed",
        "Rating": "rating",
        "Location": "location",
        "Remixer": "remixer",  # Not stored by Mixxx, set to ""
        "Tonality": "key",
        "Label": "label",  # Not stored by Mixxx, set to ""
        "Mix": "mix",  # Not stored by Mixxx, set to ""
    }

    _KEY_MAP = {
        "Abm": "1A",
        "G#m": "1A",
        "Ebm": "2A",
        "D#m": "2A",
        "Bbm": "3A",
        "A#m": "3A",
        "Fm": "4A",
        "Cm": "5A",
        "Gm": "6A",
        "Dm": "7A",
        "Am": "8A",
        "Em": "9A",
        "Bm": "10A",
        "Cbm": "10A",
        "F#m": "11A",
        "Gbm": "11A",
        "Dbm": "12A",
        "C#m": "12A",
        "B": "1B",
        "Cb": "1B",
        "F#": "2B",
        "Gb": "2B",
        "Db": "3B",
        "C#": "3B",
        "Ab": "4B",
        "G#": "4B",
        "Eb": "5B",
        "D#": "5B",
        "Bb": "6B",
        "A#": "6B",
        "F": "7B",
        "C": "8B",
        "G": "9B",
        "D": "10B",
        "A": "11B",
        "E": "12B",
    }

    _RATING_MAP = {0: 0, 1: 51, 2: 102, 3: 153, 4: 204, 5: 255}

    _COLOR_MAP = {
        "Red": ((120, 0, 0), (255, 100, 100), "0xFF0000"),
        "Orange": ((200, 100, 0), (255, 170, 80), "0xFFA500"),
        "Yellow": ((200, 200, 0), (255, 255, 150), "0xFFFF00"),
        "Green": ((0, 100, 0), (150, 255, 180), "0x00FF00"),
        "Aqua": ((0, 200, 200), (150, 255, 255), "0x25FDE9"),
        "Blue": ((0, 0, 100), (150, 150, 255), "0x0000FF"),
        "Purple": ((120, 0, 120), (200, 100, 255), "0x660099"),
        "Pink": ((200, 0, 100), (255, 200, 255), "0xFF007F"),
        "Gray": ((100, 100, 100), (180, 180, 180), "0x808080"),
        "White": ((220, 220, 220), (255, 255, 255), "0xFFFFFF"),
    }

    def __init__(self, **config):
        # Setup technical stuff
        self.logger = get_config(
            config, "logger", expected_type=logging.Logger, optional=True, default=None
        )
        self.stop_flag = get_config(
            config,
            "stop_flag",
            expected_type=threading.Event,
            optional=True,
            default=None,
        )

        # Load configuration
        self.dry_run = get_config(
            config, "dry_run", expected_type=bool, optional=True, default=True
        )
        self.mixxx_db = DATA_DIR / get_config(
            config, "mixxx_db", expected_type=str, optional=False
        )
        self.output = DATA_DIR / get_config(
            config, "output", expected_type=str, optional=True, default="rekordbox.xml"
        )
        self.hot_to_memory = get_config(
            config, "hot_to_memory", expected_type=bool, optional=True, default=False
        )
        playlist_dir_str = get_config(
            config, "playlist_dir", expected_type=str, optional=True, default=None
        )
        self.playlist_dir = Path(playlist_dir_str) if playlist_dir_str else None

        # Initialise indices
        self.mixxx_data = {}
        self.tracks = {}
        self.playlists = {}
        self.crates = {}

        # Stats
        self._tracks_processed = []

    def run(self):
        # Start timer
        start = time.time()

        # Build indices
        self.mixxx_data = self._sqlite_to_dict()
        self.tracks = self.mixxx_data["library"]

        # Process tracks
        self.logger.info("Processing tracks...")
        for track in self.tracks:
            if check_stop(self.stop_flag, self.logger):
                break
            self._tracks_processed.append(track["title"])
            self.merge_tables(track)
            self.parse_mixxx_beats(track)
            self.fix_values(track)

        if not check_stop(self.stop_flag, self.logger):
            # Build playlists
            self.build_playlists()

            # Build crates
            self.build_crates()

            # Build XML
            self.build_xml()

            # Export playlists and crates
            self.export_playlists_and_crates()

            # Final summary
            summary_items = [
                (self._tracks_processed, "Processed {} tracks."),
                (self.playlists, "Converted {} playlists."),
                (self.crates, "Converted {} crates."),
            ]

            self.logger.info(
                summary_message(
                    name="Boxxxer",
                    summary_items=summary_items,
                    dry_run=self.dry_run,
                    elapsed=time.time() - start,
                )
            )

        else:
            self.logger.info("Process interrupted by stop flag. No output generated.")

    def build_xml(self):
        self.logger.info("Building XML...")
        # Root element
        dj_playlists = ET.Element("DJ_PLAYLISTS", Version="1.0.0")

        # PRODUCT
        ET.SubElement(
            dj_playlists,
            "PRODUCT",
            Name="fuckrekordbox",
            Version="666",
            Company="PioneerOfVendorLock",
        )

        # COLLECTION
        collection = ET.SubElement(
            dj_playlists, "COLLECTION", Entries=str(len(self.tracks))
        )

        # TRACKS
        self.logger.info("Populating tracks...")
        for track in self.tracks:
            track_attribs = {}
            for xml_attr, mixxx_key in self._TRACK_MAP.items():
                if mixxx_key is not None:
                    value = track.get(mixxx_key, "")
                    track_attribs[xml_attr] = str(value)
                else:
                    track_attribs[xml_attr] = ""

            track_element = ET.SubElement(collection, "TRACK", track_attribs)

            if track.get("color"):
                track_element.set("Colour", track.get("color"))

            if track["beats"]:
                beats = track["beats"]
                window_size = 8
                if len(beats) > 1:
                    # Calculate intervals between beats
                    intervals = [beats[i + 1] - beats[i] for i in range(len(beats) - 1)]

                    # Calculate instantaneous BPMs
                    instant_bpms = [
                        60 / interval if interval > 0 else 0 for interval in intervals
                    ]

                    # Pad last value so we have the same length as beats
                    instant_bpms.append(instant_bpms[-1])

                    # Compute sliding window BPMs
                    bpm_values = []
                    for i in range(len(instant_bpms)):
                        window = instant_bpms[max(0, i - window_size + 1) : i + 1]
                        bpm_values.append(round(mean(window), 2))
                else:
                    # Fallback if there's only one beat
                    bpm_values = [str(round(track["bpm"], 2))]

                # Step 5: Add TEMPO elements to XML
                last_bpm = None
                for i, beat in enumerate(beats):
                    current_bpm = bpm_values[i]
                    if current_bpm != last_bpm:
                        ET.SubElement(
                            track_element,
                            "TEMPO",
                            Inizio=str(beat),
                            Bpm=str(current_bpm),
                            Metro="4/4",
                            Battito=str((i % 4) + 1),
                        )
                        last_bpm = current_bpm

            # CUES
            if track.get("cues", None):
                cues = track["cues"]
                for cue in cues:
                    position_mark = ET.SubElement(
                        track_element,
                        "POSITION_MARK",
                        Name="",
                        Type="0",
                        Start=str(
                            self.adjust_cue_time(
                                cue["position"], track["channels"], track["samplerate"]
                            )
                        ),
                        Num=str(cue["hotcue"] if not self.hot_to_memory else -1),
                    )

                    # The cue point
                    if cue["type"] == 2:
                        position_mark.set("Num", "-1")

                    # Hot cues and loops
                    if cue["type"] in (1, 4):
                        # Hot cue name
                        position_mark.set("Name", cue.get("label", ""))

                        # Hot cue colour
                        if cue.get("color") and not self.hot_to_memory:
                            rgb = self.decimal_to_rgb(cue.get("color"))
                            position_mark.set("Red", str(rgb[0]))
                            position_mark.set("Green", str(rgb[1]))
                            position_mark.set("Blue", str(rgb[2]))

                    # Loop end point and type
                    if cue["type"] == 4:
                        position_mark.set(
                            "End",
                            str(
                                self.adjust_cue_time(
                                    cue["position"] + cue["length"],
                                    track["channels"],
                                    track["samplerate"],
                                )
                            ),
                        )
                        position_mark.set("Type", "4")

        # PLAYLISTS
        self.logger.info("Populating playlists and crates...")
        lists = ET.SubElement(dj_playlists, "PLAYLISTS")
        lists_root = ET.SubElement(lists, "NODE", Type="0", Name="ROOT", Count="2")
        playlists = ET.SubElement(
            lists_root,
            "NODE",
            Type="0",
            Name="Playlists",
            Count=str(len(self.playlists)),
        )
        for playlist, tracks in self.playlists.items():
            node = ET.SubElement(
                playlists,
                "NODE",
                Type="1",
                Name=str(playlist),
                KeyType="0",
                Entries=str(len(tracks)),
            )
            for track in tracks:
                ET.SubElement(node, "TRACK", Key=str(track))

        # CRATES
        crates = ET.SubElement(
            lists_root, "NODE", Type="0", Name="Crates", Count=str(len(self.crates))
        )
        for crate, tracks in self.crates.items():
            node = ET.SubElement(
                crates,
                "NODE",
                Type="1",
                Name=str(crate),
                KeyType="0",
                Entries=str(len(tracks)),
            )
            for track in tracks:
                ET.SubElement(node, "TRACK", Key=str(track))

        # Build tree and save to file
        tree = ET.ElementTree(dj_playlists)
        if not self.dry_run:
            tree.write(self.output, encoding="utf-8", xml_declaration=True)
        self.logger.info(
            dry_run_message(self.dry_run, f"Saved output to {self.output}!")
        )

    def _sqlite_to_dict(self):
        try:
            conn = sqlite3.connect(self.mixxx_db)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            all_tables = [row["name"] for row in cursor.fetchall()]

            target_tables = (
                self._MIXXX_DB_INCLUDE if self._MIXXX_DB_INCLUDE else all_tables
            )
            target_tables = [t for t in target_tables if t in all_tables]

            db_dict = {}
            for table in target_tables:
                cursor.execute(f'SELECT * FROM "{table}"')
                rows = cursor.fetchall()
                db_dict[table] = [dict(row) for row in rows]

            return db_dict
        except sqlite3.Error as e:
            self.logger.error(f"SQLite error: {e}")
            return {}
        finally:
            if "conn" in locals():
                conn.close()

    def merge_tables(self, track):
        track_id = track["id"]

        # File path and size
        for location in self.mixxx_data["track_locations"]:
            if location["id"] == track_id:
                track["location"] = location["location"]
                track["filesize"] = location["filesize"]

        # Cues
        for cue in self.mixxx_data["cues"]:
            if cue["track_id"] == track_id and cue["type"] in (1, 2, 4):
                if not track.get("cues", None):
                    track["cues"] = []
                cue_attribs = {
                    k: v
                    for k, v in cue.items()
                    if k in ["color", "hotcue", "label", "length", "position", "type"]
                }
                track["cues"].append(cue_attribs)

    def build_playlists(self):
        for playlist in self.mixxx_data["Playlists"]:
            if playlist["hidden"] == 0:
                self.playlists[playlist["name"]] = []
                for track in self.mixxx_data["PlaylistTracks"]:
                    if track["playlist_id"] == playlist["id"]:
                        self.playlists[playlist["name"]].append(track["track_id"])

    def build_crates(self):
        for crate in self.mixxx_data["crates"]:
            if crate["show"] == 1:
                self.crates[crate["name"]] = []
                for track in self.mixxx_data["crate_tracks"]:
                    if track["crate_id"] == crate["id"]:
                        self.crates[crate["name"]].append(track["track_id"])

    def export_playlists_and_crates(self):
        if not self.dry_run and self.playlist_dir:
            self.playlist_dir.mkdir(parents=True, exist_ok=True)

            # Define collections and their corresponding subdirectories
            subdirs = {
                "Playlists": self.playlists,
                "Crates": self.crates,
            }

            for subdir_name, collection in subdirs.items():
                if not collection:
                    continue

                for name, tracks in collection.items():
                    if not tracks:
                        continue

                    subdir_path = self.playlist_dir / subdir_name
                    subdir_path.mkdir(parents=True, exist_ok=True)

                    playlist_file = subdir_path / f"{name.replace(' ', '_')}.m3u8"

                    with playlist_file.open("w", encoding="utf-8") as f:
                        f.write("#EXTM3U\n")
                        for track in tracks:
                            for file in self.mixxx_data["track_locations"]:
                                if track == file["id"]:
                                    f.write(f"{file['location']}\n")

    def fix_values(self, track):
        # Filetype
        if track["filetype"] == "flac":
            track["filetype"] = "FLAC File"

        # Filepath
        track["location"] = "file://localhost/" + track["location"].replace(" ", "%20")

        # Round duration to nearest second
        track["duration"] = str(round(track["duration"]))

        # Format date to YYYY-MM-DD
        track["datetime_added"] = track["datetime_added"][:10]

        # Standardise key
        if track["key"] != "":
            track["key"] = self._KEY_MAP[track["key"]]

        # Round BPM to 2 decimal places
        if track["bpm"]:
            track["bpm"] = round(track["bpm"], 2)

        # Map rating
        if track["rating"]:
            track["rating"] = self._RATING_MAP[track["rating"]]
        else:
            track["rating"] = 0

        # Genre
        if not track["genre"]:
            track["genre"] = ""

        # Map colour
        if track.get("color"):
            track["grouping"] = self.classify_rgb(*self.decimal_to_rgb(track["color"]))[
                0
            ]
            track["color"] = self.classify_rgb(*self.decimal_to_rgb(track["color"]))[1]
        else:
            track["grouping"] = ""

        # Fields that Mixxx doesn"t store
        track["discnumber"] = 0
        track["composer"] = ""
        track["remixer"] = ""
        track["label"] = ""
        track["mix"] = ""

    def adjust_cue_time(self, samples, channels, samplerate):
        return f"{samples / channels / samplerate:.3f}"

    def adjust_beat_time(self, frame_position, samplerate, bpm):
        position_seconds = frame_position / samplerate
        if bpm and bpm > 0:
            beat_length = 60.0 / bpm
            if position_seconds < 0:
                position_seconds += beat_length
            elif position_seconds > beat_length:
                position_seconds -= beat_length
        return f"{position_seconds:.3f}"

    def decimal_to_rgb(self, decimal):
        r = (decimal >> 16) & 0xFF
        g = (decimal >> 8) & 0xFF
        b = decimal & 0xFF
        return r, g, b

    def classify_rgb(self, r, g, b):
        for color_str, (min_rgb, max_rgb, color_hex) in self._COLOR_MAP.items():
            if (
                min_rgb[0] <= r <= max_rgb[0]
                and min_rgb[1] <= g <= max_rgb[1]
                and min_rgb[2] <= b <= max_rgb[2]
            ):
                return color_str, color_hex
        return "Unknown"

    def parse_mixxx_beats(self, track):
        beats_blob = track.get("beats")
        beats_version = track.get("beats_version", "")
        samplerate = track.get("samplerate")
        bpm = track.get("bpm")

        if not beats_blob or not samplerate:
            return

        beat_times = []

        if beats_version.startswith("BeatMap"):
            try:
                beats_proto = _beats_pb2.BeatMap()
                beats_proto.ParseFromString(beats_blob)

                for beat in beats_proto.beat:
                    frame_position = beat.frame_position
                    time_seconds = float(
                        self.adjust_beat_time(frame_position, samplerate, bpm)
                    )
                    beat_times.append(time_seconds)

            except DecodeError as e:
                self.logger.warning(f"Failed to decode BeatMap protobuf: {e}")
            except (TypeError, ValueError, AttributeError) as e:
                self.logger.warning(f"Invalid data in BeatMap: {e}")

        elif beats_version.startswith("BeatGrid"):
            try:
                beats_proto = _beats_pb2.BeatGrid()
                beats_proto.ParseFromString(beats_blob)

                if beats_proto.HasField("first_beat"):
                    frame_position = beats_proto.first_beat.frame_position
                    time_seconds = float(
                        self.adjust_beat_time(frame_position, samplerate, bpm)
                    )
                    beat_times.append(time_seconds)

            except DecodeError as e:
                self.logger.warning(f"Failed to decode BeatGrid protobuf: {e}")
            except (TypeError, ValueError, AttributeError) as e:
                self.logger.warning(f"Invalid data in BeatGrid: {e}")

        if beat_times:
            track["beats"] = beat_times
