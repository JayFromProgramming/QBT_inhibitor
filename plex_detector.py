import asyncio
import traceback
import netifaces

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
        self.local_subnets = []
        self._get_host_names()

    def _get_host_names(self):
        """
        Gets all the ip addresses that can be bound to
        """
        interfaces = []
        for interface in netifaces.interfaces():
            try:
                if netifaces.AF_INET in netifaces.ifaddresses(interface):
                    for link in netifaces.ifaddresses(interface)[netifaces.AF_INET]:
                        if link["addr"] != "":
                            interfaces.append(link["addr"])
            except Exception as e:
                logging.debug(f"Error getting interface {interface}: {e}")
                pass
        for interface in interfaces:
            logging.debug(f"Found interface {interface}")
            self.local_subnets.append(".".join(interface.split(".")[0:3]))

    def _get_activity(self):
        should_throttle = False
        try:
            sessions = self.plex_server.sessions()
            self.interface_class.total_sessions = 0
            for session in sessions:
                try:
                    if session.players[0].state == "playing" or session.players[0].state == "buffering":
                        if any([session.players[0].address.startswith(subnet) for subnet in self.local_subnets]):
                            logging.debug(f"Player {session.players[0].address} is on the same subnet as the server")
                            continue
                        should_throttle = True
                        self.interface_class.total_sessions += 1
                except Exception as e:
                    logging.error(f"Failed to get session info: {e}")
                    logging.error(traceback.format_exc())
        except Exception as e:
            logging.error(f"Failed to get plex activity: {e}\n{traceback.format_exc()}")
            self.interface_class.connected_to_plex = False
        else:
            self.interface_class.connected_to_plex = True
        return should_throttle

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

