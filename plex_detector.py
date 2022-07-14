import asyncio
import traceback

from plexapi.server import PlexServer

from helpers import PlexInhibitor, InhibitSource

import logging

logging.getLogger(__name__).setLevel(logging.DEBUG)


class PlexDetector:
    """Detects if anyone is streaming on a Plex server, and if so it determines if qbittorrent should have its upload
    throttled"""

    def __init__(self, plex_url, plex_token, interface_class=PlexInhibitor):
        logging.info(f"Initializing plexDetector, connecting to {plex_url}")
        self.plex_url = plex_url
        self.plex_token = plex_token
        try:
            self.plex_server = PlexServer(self.plex_url, self.plex_token)
        except Exception as e:
            logging.error(f"Failed to connect to {plex_url}: {e}")
            self.plex_server = None
        self.interface_class = interface_class
        logging.info(f"Connected to {plex_url}")
        self.interface_class.connected_to_plex = True

    def _get_activity(self):
        try:
            sessions = self.plex_server.sessions()
            should_throttle = False
            self.interface_class.total_sessions = 0
            for session in sessions:
                if session.players[0].state == "playing":
                    if session.sessions[0].location == "lan":
                        continue
                    should_throttle = True
                    self.interface_class.total_sessions += 1
            return should_throttle
        except Exception as e:
            logging.error(f"Failed to get plex activity: {e}\n{traceback.format_exc()}")
            self.interface_class.connected_to_plex = False

    def get_activity(self):
        return self._get_activity()

    async def run(self):
        while not self.interface_class.shutdown:
            logging.debug("Checking plex activity")
            if self._get_activity():
                self.interface_class.should_inhibit = True
            else:
                self.interface_class.should_inhibit = False
            await asyncio.sleep(5)

