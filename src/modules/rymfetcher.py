import webbrowser
from utils import banner_message


class Rymfetcher:
    """
    Opens RYM album collection in a web browser.
    """

    def __init__(self, **config):
        self.username = config.get("username", None)

    def run(self):
        if not self.username:
            raise ValueError("Username must be provided to open the collection.")

        url = f"https://rateyourmusic.com/collection_p/{self.username}/d.rp,albjh,tn,v,o,g,n9999999"
        print(f"Opening collection URL: {url}")
        webbrowser.open(url)
        print(banner_message("Returning..."))
