import sqlite3
import xml.etree.ElementTree as ET
import time
from utils import *
import beats_pb2


class Boxxxer:
    """
    Exports an XML of your Mixxx library to be imported into Rekordbox.
    """

    def __init__(self, **config):
        # Setup logger
        self.logger = setup_logger(
            name=Path(__file__).stem,
            base_dir=Path(__file__).resolve().parents[2],
            console_level=config.get('console_level', 'DEBUG'),
            file_level=config.get('file_level', 'DEBUG')
        )

        # Stop flag (for safe quitting)
        self.stop_flag = config.get("stop_flag")

        # Load configuration
        self.mixxx_db = Path(config['mixxx_db'])
        self.dry_run = config.get('dry_run', True)
        self.output = config.get('output', 'rekordbox.xml')

        # Initialise indices
        self.mixxx_data = {}
        self.tracks = {}
        self.playlists = {}
        self.crates = {}

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
            'DiscNumber': None,
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
            'Remixer': None,
            'Tonality': 'key',
            'Label': None,
            'Mix': None
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

    def run(self):
        # Start timer
        self.start_time = time.time()

        # Build indices
        self.mixxx_data = self._sqlite_to_dict()
        self.tracks = self.mixxx_data['library']

        # Process tracks
        for i, track in enumerate(self.tracks):
            if check_stop(self.stop_flag, self.logger):
                break
            self.logger.info(
                processing_message(
                    current=i,
                    total=len(self.tracks),
                    file=track['title'],
                    elapsed=time.time() - self.start_time
                )
            )
            self.merge_tables(track)
            self.parse_mixxx_beats(track)
            self.fix_values(track)
        self.build_playlists()
        self.build_crates()
        self.build_xml()

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

            # TEMPO
            if track['beats']:
                beats = track['beats']
                if beats['type'] == "BeatMap":
                    for beat in beats['beats']:
                        ET.SubElement(track_element, "TEMPO", Inizio=str(beat['time_seconds']), Bpm=str(round(track['bpm'], 2)), Metro="4/4", Battito="1")
                elif beats['type'] == "BeatGrid":
                    ET.SubElement(track_element, "TEMPO", Inizio=str(beats['first_beat']['time_seconds']), Bpm=str(round(beats['bpm_info']['bpm'], 2)), Metro="4/4", Battito="1")

            # CUES
            if track.get('cues', None):
                cues = track['cues']
                for cue in cues:
                    position_mark = ET.SubElement(track_element, "POSITION_MARK", Name=str(cue["label"]), Type="0", Start=str(self.sample_to_seconds(cue["position"], track["samplerate"], 3)), Num=str(cue["hotcue"]))
                    if cue['length'] > 0:
                        position_mark.set(
                            "End",
                            str(self.sample_to_seconds(cue['position'] + cue['length'], track['samplerate'], 3))
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
                track['location'] = "file://localhost/" + location['location'].replace(' ', '%20')
                track['filesize'] = location['filesize']

        # Cues
        for cue in self.mixxx_data['cues']:
            if cue['track_id'] == track_id:
                if not track.get('cues', None):
                    track['cues'] = []
                cue_attribs = {k: v for k, v in cue.items() if k in ['color', 'hotcue', 'label', 'length', 'position']}
                track['cues'].append(cue_attribs)


    def build_playlists(self):
        self.logger.debug("Building playlists...")
        for playlist in self.mixxx_data['Playlists']:
            if playlist['hidden'] == 0:
                playlist_name = playlist['name']
                playlist_id = playlist['id']
                for track in self.mixxx_data['PlaylistTracks']:
                    if track['playlist_id'] == playlist_id:
                        if playlist_name not in self.playlists:
                            self.playlists[playlist_name] = []
                        self.playlists[playlist_name].append(track['track_id'])

    def build_crates(self):
        self.logger.debug("Building crates...")
        for crate in self.mixxx_data['crates']:
            if crate['show'] == 1:
                crate_name = crate['name']
                crate_id = crate['id']
                for track in self.mixxx_data['crate_tracks']:
                    if track['crate_id'] == crate_id:
                        if crate_name not in self.crates:
                            self.crates[crate_name] = []
                        self.crates[crate_name].append(track['track_id'])

    def fix_values(self, track):
        self.logger.debug("Fixing values for compatibility...")
        if track['filetype'] == 'flac':
            track['filetype'] = 'FLAC File'
        track['duration'] = str(round(track['duration']))
        track['datetime_added'] = track['datetime_added'][:10]
        if track['grouping'] == 'None':
            track['grouping'] = ''
        if track['key'] != '':
            track['key'] = self.KEY_MAP[track['key']]
        if track['bpm']:
            track['bpm'] = round(track['bpm'], 2)
    
    def sample_to_seconds(self, samples, samplerate, rounding=3):
        return round(samples / samplerate, rounding)

    def parse_mixxx_beats(self, track):
        self.logger.debug("Parsing beat information...")
        source_enum_map = {
            beats_pb2.ANALYZER: "ANALYZER",
            beats_pb2.FILE_METADATA: "FILE_METADATA",
            beats_pb2.USER: "USER"
        }

        track_id = track.get("id")
        beats_blob = track.get("beats")
        beats_version = track.get("beats_version", "")

        if not beats_blob:
            return

        if beats_version.startswith("BeatMap"):
            try:
                beats_proto = beats_pb2.BeatMap()
                beats_proto.ParseFromString(beats_blob)

                beats_list = []
                for beat in beats_proto.beat:
                    frame_position = beat.frame_position

                    beats_list.append({
                        "frame_position": frame_position,
                        "enabled": beat.enabled,
                        "source": source_enum_map.get(beat.source, f"Unknown({beat.source})"),
                        "time_seconds": self.sample_to_seconds(frame_position, track["samplerate"], 3)
                    })

                if beats_list:
                    track['beats'] = {
                        "type": "BeatMap",
                        "beats": beats_list
                    }
            except Exception as e:
                self.logger.warning(f"Failed to parse BeatMap for track_id {track_id}: {e}")

        elif beats_version.startswith("BeatGrid"):
            try:
                beats_proto = beats_pb2.BeatGrid()
                beats_proto.ParseFromString(beats_blob)

                bpm_info = {}
                if beats_proto.HasField('bpm'):
                    bpm_info = {
                        "bpm": beats_proto.bpm.bpm,
                        "source": source_enum_map.get(beats_proto.bpm.source, f"Unknown({beats_proto.bpm.source})")
                    }

                first_beat = None
                if beats_proto.HasField('first_beat'):
                    fb = beats_proto.first_beat
                    frame_position = fb.frame_position
                    first_beat = {
                        "frame_position": frame_position,
                        "enabled": fb.enabled,
                        "source": source_enum_map.get(fb.source, f"Unknown({fb.source})"),
                        "time_seconds": self.sample_to_seconds(frame_position, track["samplerate"], 3)
                    }

                track['beats'] = {
                    "type": "BeatGrid",
                    "bpm_info": bpm_info,
                    "first_beat": first_beat,
                }

            except Exception as e:
                self.logger.warning(f"Failed to parse BeatGrid for track_id {track_id}: {e}")
