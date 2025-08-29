import webbrowser
from pathlib import Path
from utils import setup_logger, banner_message


class Rymfetcher:
    """
    Opens RYM album collection in a web browser.
    """

    def __init__(self, **config):
        self.logger = config.get('logger')
        self.username = config.get('username', None)

    def run(self):
        if not self.username:
            raise ValueError("Username must be provided to open the collection.")

        url = f"https://rateyourmusic.com/collection_p/{self.username}/d.rp,albjh,tn,v,o,g,n9999999"
        self.logger.info(f"Opening collection URL: {url}")
        webbrowser.open(url)
        self.logger.info(banner_message("Returning..."))
