import sqlite3
import xml.etree.ElementTree as ET
import time
from utils import *
import modules._beats_pb2 as _beats_pb2


class Boxxxer:
    """
    Exports an XML of your Mixxx library to be imported into Rekordbox.
    """

    def __init__(self, **config):
        # Setup logger
        self.logger = config.get('logger')

        # Stop flag (for safe quitting)
        self.stop_flag = config.get("stop_flag")

        # Load configuration
        self.mixxx_db = Path(__file__).resolve().parents[2] / "data" / config.get('mixxx_db')
        self.dry_run = config.get('dry_run', True)
        self.output = Path(__file__).resolve().parents[2] / "data" / config.get('output', 'rekordbox.xml')
        self.hot_to_memory = config.get('hot_to_memory', False)

        # Initialise indices
        self.mixxx_data = {}
        self.tracks = {}
        self.playlists = {}
        self.crates = {}

        # Stats
        self._tracks_processed = []

        # Mappings
        self.MIXXX_DB_INCLUDE = [
            'PlaylistTracks',
            'Playlists',
            'crate_tracks',
            'crates',
            'cues',
            'library',
            'track_locations'
        ]

        self.TRACK_MAP = {
            'TrackID': 'id',
            'Name': 'title',
            'Artist': 'artist',
            'Composer': 'composer',
            'Album': 'album',
            'Grouping': 'grouping',
            'Genre': 'genre',
            'Kind': 'filetype',
            'Size': 'filesize',
            'TotalTime': 'duration',
            'DiscNumber': 'discnumber', # Not store by Mixxx, set to 0
            'TrackNumber': 'tracknumber',
            'Year': 'year',
            'AverageBpm': 'bpm',
            'DateAdded': 'datetime_added',
            'BitRate': 'bitrate',
            'SampleRate': 'samplerate',
            'Comments': 'comment',
            'PlayCount': 'timesplayed',
            'Rating': 'rating',
            'Location': 'location',
            'Remixer': 'remixer', # Not store by Mixxx, set to ""
            'Tonality': 'key',
            'Label': 'label', # Not store by Mixxx, set to ""
            'Mix': 'mix', # Not store by Mixxx, set to ""
        }

        self.KEY_MAP = {
            'Abm': '1A',
            'G#m': '1A',
            'Ebm': '2A',
            'D#m': '2A',
            'Bbm': '3A',
            'A#m': '3A',
            'Fm': '4A',
            'Cm': '5A',
            'Gm': '6A',
            'Dm': '7A',
            'Am': '8A',
            'Em': '9A',
            'Bm': '10A',
            'Cbm': '10A',
            'F#m': '11A',
            'Gbm': '11A',
            'Dbm': '12A',
            'C#m': '12A',
            'B': '1B',
            'Cb': '1B',
            'F#': '2B',
            'Gb': '2B',
            'Db': '3B',
            'C#': '3B',
            'Ab': '4B',
            'G#': '4B',
            'Eb': '5B',
            'D#': '5B',
            'Bb': '6B',
            'A#': '6B',
            'F': '7B',
            'C': '8B',
            'G': '9B',
            'D': '10B',
            'A': '11B',
            'E': '12B',
        }

        self.RATING_MAP = {
            0: 0,
            1: 51,
            2: 102,
            3: 153,
            4: 204,
            5: 255
        }

        self.COLOR_MAP = {
            "Red":    ((120,   0,   0), (255, 100, 100), "0xFF0000"),
            "Orange": ((200, 100,   0), (255, 170,  80), "0xFFA500"),
            "Yellow": ((200, 200,   0), (255, 255, 150), "0xFFFF00"),
            "Green":  ((  0, 100,   0), (150, 255, 180), "0x00FF00"),
            "Aqua":   ((  0, 200, 200), (150, 255, 255), "0x25FDE9"),
            "Blue":   ((  0,   0, 100), (150, 150, 255), "0x0000FF"),
            "Purple": ((120,   0, 120), (200, 100, 255), "0x660099"),
            "Pink":   ((200,   0, 100), (255, 200, 255), "0xFF007F"),
            "Gray":   ((100, 100, 100), (180, 180, 180), "0x808080"),
            "White":  ((220, 220, 220), (255, 255, 255), "0xFFFFFF")
        }

    def run(self):
        # Start timer
        self.start_time = time.time()

        # Build indices
        self.mixxx_data = self._sqlite_to_dict()
        self.tracks = self.mixxx_data['library']

        # Process tracks
        for track in self.tracks:
            if check_stop(self.stop_flag, self.logger):
                break
            self._tracks_processed.append(track['title'])
            self.logger.info(
                processing_message(
                    current=len(self._tracks_processed),
                    total=len(self.tracks),
                    file=track['title'],
                    elapsed=time.time() - self.start_time
                )
            )
            self.merge_tables(track)
            self.parse_mixxx_beats(track)
            self.fix_values(track)

        # Build playlists
        self.build_playlists()

        # Build crates
        self.build_crates()

        # Build XML
        self.build_xml()

        # Final summary
        summary_items = [
            (self._tracks_processed, "Processed {} tracks.")
        ]

        self.logger.info(
            summary_message(
                name="Boxxxer",
                summary_items=summary_items,
                dry_run=self.dry_run,
                elapsed=time.time() - self.start_time
            )
        )

    def build_xml(self):
        self.logger.info("Building XML...")
        # Root element
        dj_playlists = ET.Element("DJ_PLAYLISTS", Version="1.0.0")

        # PRODUCT
        ET.SubElement(dj_playlists, "PRODUCT", Name="fuckrekordbox", Version="666", Company="PioneerOfVendorLock")

        # COLLECTION
        collection = ET.SubElement(dj_playlists, "COLLECTION", Entries=str(len(self.tracks)))

        # TRACKS
        self.logger.debug("Populating tracks...")
        for track in self.tracks:
            track_attribs = {}
            for xml_attr, mixxx_key in self.TRACK_MAP.items():
                if mixxx_key is not None:
                    value = track.get(mixxx_key, "")
                    track_attribs[xml_attr] = str(value)
                else:
                    track_attribs[xml_attr] = ""

            track_element = ET.SubElement(collection, "TRACK", track_attribs)

            if track.get('color'):
                track_element.set(
                    "Colour",
                    track.get('color')
                )

            # TEMPO
            if track['beats']:
                for i, beat in enumerate(track['beats']):
                    ET.SubElement(
                        track_element,
                        "TEMPO",
                        Inizio=str(beat),
                        Bpm=str(round(track['bpm'], 2)),
                        Metro="4/4",
                        Battito=str((i % 4) + 1)
                    )

            # CUES
            if track.get('cues', None):
                cues = track['cues']
                for cue in cues:
                    position_mark = ET.SubElement(
                        track_element,
                        "POSITION_MARK",
                        Name="",
                        Type="0",
                        Start=str(self.adjust_cue_time(cue["position"], track["channels"], track["samplerate"])),
                        Num=str(cue["hotcue"] if not self.hot_to_memory else -1)
                    )

                    # The cue point
                    if cue['type'] == 2:
                        position_mark.set(
                            "Num",
                            "-1"
                        )

                    # Hot cues and loops
                    if cue['type'] in (1, 4):
                        # Hot cue name
                        position_mark.set(
                            "Name",
                            cue.get('label', "")
                        )

                        # Hot cue colour
                        if cue.get('color') and not self.hot_to_memory:
                            rgb = self.decimal_to_rgb(cue.get('color'))
                            position_mark.set(
                                "Red",
                                str(rgb[0])
                            )
                            position_mark.set(
                                "Green",
                                str(rgb[1])
                            )
                            position_mark.set(
                                "Blue",
                                str(rgb[2])
                            )
                    
                    # Loop end point and type
                    if cue['type'] == 4:
                        position_mark.set(
                            "End",
                            str(self.adjust_cue_time(cue['position'] + cue['length'], track["channels"], track['samplerate']))
                        )
                        position_mark.set(
                            "Type",
                            "4"
                        )

        # PLAYLISTS
        self.logger.debug("Populating playlists...")
        lists = ET.SubElement(dj_playlists, "PLAYLISTS")
        lists_root = ET.SubElement(lists, "NODE", Type="0", Name="ROOT", Count="2")
        playlists = ET.SubElement(lists_root, "NODE", Type="0", Name="Playlists", Count=str(len(self.playlists)))
        for playlist in self.playlists:
            node = ET.SubElement(playlists, "NODE", Type="1", Name=str(playlist), KeyType="0", Entries=str(len(self.playlists[playlist])))
            for track in self.playlists[playlist]:
                ET.SubElement(node, "TRACK", Key=str(track))

        # CRATES
        self.logger.debug("Populating crates...")
        crates = ET.SubElement(lists_root, "NODE", Type="0", Name="Crates", Count=str(len(self.crates)))
        for crate in self.crates:
            node = ET.SubElement(crates, "NODE", Type="1", Name=str(crate), KeyType="0", Entries=str(len(self.crates[crate])))
            for track in self.crates[crate]:
                ET.SubElement(node, "TRACK", Key=str(track))

        # Build tree and save to file
        tree = ET.ElementTree(dj_playlists)
        if not self.dry_run:
            tree.write(self.output, encoding="utf-8", xml_declaration=True)
        self.logger.info(dry_run_message(self.dry_run, f"Saved output to {self.output}!"))

    def _sqlite_to_dict(self):
        self.logger.debug(f"Parsing {self.mixxx_db}...")
        try:
            conn = sqlite3.connect(self.mixxx_db)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            all_tables = [row['name'] for row in cursor.fetchall()]

            target_tables = self.MIXXX_DB_INCLUDE if self.MIXXX_DB_INCLUDE else all_tables
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
            if 'conn' in locals():
                conn.close()

    def merge_tables(self, track):
        self.logger.debug("Merging tables...")
        track_id = track['id']

        # File path and size
        for location in self.mixxx_data['track_locations']:
            if location['id'] == track_id:
                track['location'] = location['location']
                track['filesize'] = location['filesize']

        # Cues
        for cue in self.mixxx_data['cues']:
            if cue['track_id'] == track_id and cue['type'] in (1, 2, 4):
                if not track.get('cues', None):
                    track['cues'] = []
                cue_attribs = {k: v for k, v in cue.items() if k in ['color', 'hotcue', 'label', 'length', 'position', 'type']}
                track['cues'].append(cue_attribs)

    def build_playlists(self):
        self.logger.debug("Building playlists...")
        for playlist in self.mixxx_data['Playlists']:
            if playlist['hidden'] == 0:
                self.playlists[playlist['name']] = []
                for track in self.mixxx_data['PlaylistTracks']:
                    if track['playlist_id'] == playlist['id']:
                        self.playlists[playlist['name']].append(track['track_id'])

    def build_crates(self):
        self.logger.debug("Building crates...")
        for crate in self.mixxx_data['crates']:
            if crate['show'] == 1:
                self.crates[crate['name']] = []
                for track in self.mixxx_data['crate_tracks']:
                    if track['crate_id'] == crate['id']:
                        self.crates[crate['name']].append(track['track_id'])

    def fix_values(self, track):
        self.logger.debug("Fixing values for compatibility...")

        # Filetype
        if track['filetype'] == 'flac':
            track['filetype'] = 'FLAC File'

        # Filepath
        track['location'] = "file://localhost/" + track['location'].replace(' ', '%20')

        # Round duration to nearest second
        track['duration'] = str(round(track['duration']))

        # Format date to YYYY-MM-DD
        track['datetime_added'] = track['datetime_added'][:10]

        # Standardise key
        if track['key'] != '':
            track['key'] = self.KEY_MAP[track['key']]

        # Round BPM to 2 decimal places
        if track['bpm']:
            track['bpm'] = round(track['bpm'], 2)

        # Map rating
        if track['rating']:
            track['rating'] = self.RATING_MAP[track['rating']]
        else:
            track['rating'] = 0

        # Genre
        if not track['genre']:
            track['genre'] = ""

        # Map colour
        if track.get('color'):
            track['grouping'] = self.classify_rgb(*self.decimal_to_rgb(track['color']))[0]
            track['color'] = self.classify_rgb(*self.decimal_to_rgb(track['color']))[1]
        else:
            track['grouping'] = ""
        
        # Fields that Mixxx doesn't store
        track['discnumber'] = 0
        track['composer'] = ""
        track['remixer'] = ""
        track['label'] = ""
        track['mix'] = ""

    def adjust_cue_time(self, samples, channels, samplerate):
        return "{:.3f}".format(samples / channels / samplerate)

    def adjust_beat_time(self, frame_position, samplerate, bpm):
        position_seconds = frame_position / samplerate
        if bpm and bpm > 0:
            beat_length = 60.0 / bpm
            if position_seconds < 0:
                position_seconds += beat_length
            elif position_seconds > beat_length:
                position_seconds -= beat_length
        return "{:.3f}".format(position_seconds)

    def decimal_to_rgb(self, decimal):
        r = (decimal >> 16) & 0xFF
        g = (decimal >> 8) & 0xFF
        b = decimal & 0xFF
        return r, g, b

    def classify_rgb(self, r, g, b):
        for color_str, (min_rgb, max_rgb, color_hex) in self.COLOR_MAP.items():
            if (
                min_rgb[0] <= r <= max_rgb[0] and
                min_rgb[1] <= g <= max_rgb[1] and
                min_rgb[2] <= b <= max_rgb[2]
            ):
                return color_str, color_hex
        return "Unknown"

    def parse_mixxx_beats(self, track):
        self.logger.debug("Parsing beat information...")
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
                    time_seconds = self.adjust_beat_time(frame_position, samplerate, bpm)
                    beat_times.append(time_seconds)

            except Exception as e:
                self.logger.warning(f"Failed to parse BeatMap: {e}")

        elif beats_version.startswith("BeatGrid"):
            try:
                beats_proto = _beats_pb2.BeatGrid()
                beats_proto.ParseFromString(beats_blob)

                if beats_proto.HasField("first_beat"):
                    frame_position = beats_proto.first_beat.frame_position
                    time_seconds = self.adjust_beat_time(frame_position, samplerate, bpm)
                    beat_times.append(time_seconds)

            except Exception as e:
                self.logger.warning(f"Failed to parse BeatGrid: {e}")

        if beat_times:
            track['beats'] = beat_times
