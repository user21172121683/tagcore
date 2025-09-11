from html.parser import HTMLParser
import re


class Rymparser(HTMLParser):
    """Parses RYM collection HTML."""

    # TODO: fix catalog number
    def __init__(self):
        super().__init__()
        self.flags = {
            "album": False,
            "album_name": False,
            "date": False,
            "rating": False,
            "label": False,
            "ownership": False,
            "genre_link": False,
            "label_catalognr": False,
            "credited_name": False,
            "artist": False,
            "collab": False,
            "tagcloud": False,
            "tag": False,
        }
        self.albums = []

        self.just_saw_label_link = False

        self.current_album = {}
        self.collab_name = []
        self.current_artist = {}
        self.current_genre = {}
        self.current_label = {}
        self.current_album_name = {}

        self.reset_current_album()

    def reset_current_album(self):
        self.current_album = {
            "artist": [],
            "album": {},
            "genre": [],
            "rating": "",
            "label": {},
            "ownership": "",
            "date": "",
            "tag": [],
        }
        self.collab_name = []
        self.current_artist = {}
        self.current_genre = {}
        self.current_label = {}
        self.current_album_name = {}

    def handle_starttag(self, tag: str, attrs):
        attrs_dict = dict(attrs)

        if tag == "tr" and attrs_dict.get("id", "").startswith("page_catalog_item_"):
            self.flags["album"] = True
            self.reset_current_album()

        if not self.flags["album"]:
            return

        title = attrs_dict.get("title", "")
        class_attr = attrs_dict.get("class", "")

        if tag == "a" and title:
            self._handle_start_a_tag(title)

        elif tag == "a" and self.flags["tagcloud"]:
            self.flags["tag"] = True  # Temporary flag just for one tag link

        elif tag == "div" and "or_q_tagcloud" in class_attr:
            self.flags["tagcloud"] = True

        elif tag == "span" and "smallgray" in class_attr:
            self.flags["date"] = True

        elif tag == "span" and "credited_name" in class_attr:
            self.flags["credited_name"] = True
            self.flags["collab"] = True

        elif tag == "td":
            self._handle_start_td_tag(class_attr)

        elif tag == "div" and "smallgray" in class_attr:
            self.flags["label_catalognr"] = True

    def _handle_start_a_tag(self, title: str):
        id_extracted = self._extract_id(title, include_brackets=True)

        if "Artist" in title:
            self.flags["artist"] = True
            self.current_artist = {"artist_name": None, "artist_id": id_extracted}
        elif "Album" in title:
            self.flags["album_name"] = True
            self.current_album_name = {"album_title": None, "album_id": id_extracted}
        elif "Genre" in title:
            self.flags["genre_link"] = True
            self.current_genre = {"genre_name": None, "genre_id": id_extracted}
        elif "Label" in title:
            self.flags["label"] = True
            self.just_saw_label_link = True
            self.current_label = {"label_name": None, "label_id": id_extracted}

    def _handle_start_td_tag(self, class_attr: str):
        if "or_q_rating" in class_attr:
            self.flags["rating"] = True
        elif "or_q_ownership" in class_attr:
            self.flags["ownership"] = True

    def handle_endtag(self, tag: str):
        if tag == "tr" and self.flags["album"]:
            self._finalize_current_album()
            self.flags["album"] = False

        if not self.flags["album"]:
            return

        if tag == "a":
            self._handle_end_a_tag()
        elif tag == "span":
            self.flags["date"] = False
            self.flags["credited_name"] = False
            self.flags["collab"] = False
        elif tag == "td":
            self.flags["rating"] = False
            self.flags["ownership"] = False
        elif tag == "div":
            self.flags["label_catalognr"] = False

        if tag == "div" and self.flags["tagcloud"]:
            self.flags["tagcloud"] = False

        if tag == "a" and self.flags.get("tag"):
            self.flags["tag"] = False

    def _handle_end_a_tag(self):
        if self.flags["artist"] and self.current_artist.get("artist_name"):
            self.current_album["artist"].append(self.current_artist.copy())
        self.flags["artist"] = False

        if self.flags["album_name"] and self.current_album_name.get("album_title"):
            self.current_album["album"] = self.current_album_name.copy()
        self.flags["album_name"] = False

        if self.flags["genre_link"] and self.current_genre.get("genre_name"):
            self.current_album["genre"].append(self.current_genre.copy())
        self.flags["genre_link"] = False

        if self.flags["label"] and self.current_label.get("label_name"):
            self.current_album["label"] = self.current_label.copy()
        self.flags["label"] = False

    def handle_data(self, data: str):
        if not self.flags["album"]:
            return

        data = data.strip()
        if not data:
            return

        handlers = {
            "artist": lambda: self._append("current_artist", "artist_name", data),
            "album_name": lambda: self._append(
                "current_album_name", "album_title", data
            ),
            "label": lambda: self._append("current_label", "label_name", data),
            "genre_link": lambda: self._append("current_genre", "genre_name", data),
        }

        for flag, handler in handlers.items():
            if self.flags[flag]:
                handler()

        if self.flags["tag"]:
            self.current_album["tag"].append(data)

        if self.flags["label_catalognr"]:
            data = data.strip()
            if not data or data.lower() == "n/a":
                return
            if "label_catalognr" not in self.current_label and ":" in data:
                data = data.rstrip("|").strip()
                self.current_label["label_catalognr"] = data

        if self.flags["date"]:
            self.current_album["date"] = data.replace("(", "").replace(")", "")

        if self.flags["rating"]:
            self.current_album["rating"] = data

        if self.flags["ownership"]:
            self.current_album["ownership"] = data

        if self.flags["credited_name"]:
            self.collab_name.append(data)

    def _append(self, obj_attr: str, key: str, new_data: str):
        obj = getattr(self, obj_attr)
        existing = obj.get(key)
        obj[key] = new_data if existing is None else f"{existing} {new_data}"

    def _append_data(self, original, new_data):
        return new_data if original is None else f"{original} {new_data}"

    def _extract_id(self, title: str, include_brackets: bool = False):
        match = re.search(r"\[(.*?)]", title)
        if match:
            return f"[{match.group(1)}]" if include_brackets else match.group(1)
        return None

    def _finalize_current_album(self):
        if self.collab_name:
            self.current_album["artist"].append(
                {"artist_collab": " ".join(self.collab_name)}
            )

        if not isinstance(self.current_album["genre"], list):
            self.current_album["genre"] = []

        self.albums.append(self.current_album)
