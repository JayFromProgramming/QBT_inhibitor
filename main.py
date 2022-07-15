import datetime
import json

from qbittorrent import Client

import asyncio

from net_detector import NetDetector
from plex_detector import PlexDetector
from web_api import WebAPI
from helpers import InhibitSource, PlexInhibitor, WebInhibitor, APIInhibitor, InhibitHolder, NetInhibitor
import logging
import auto_update

logging.basicConfig(level=logging.INFO,
                    format=r"[%(asctime)s - %(levelname)s - %(threadName)s - %(name)s - %(funcName)s - %(message)s]")


class qbtInhibitor:

    def __init__(self, qbt_url, qbt_username, qbt_password, plex_url, plex_token, api_ip, main_limit=None,
                 alt_limit=None):
        self.qbt_url = qbt_url
        self.qbt_username = qbt_username
        self.qbt_password = qbt_password
        self.plex_url = plex_url
        self.plex_token = plex_token
        self.qbt = Client(self.qbt_url)
        self.qbt_connected = False
        self.qbt_was_connected = True

        self.api_ip = api_ip
        self.webapi = None

        self.qbt_main_limit = main_limit
        self.qbt_alt_limit = alt_limit

        self.stop = False

        self.last_inhibit_sources = []  # This is to keep track of changes in the inhibit sources

        self.inhibit_sources = InhibitHolder()
        self.tasks = []
        self.inhibiting = False  # This is a flag to indicate if we are currently inhibiting or not

        self.updater = auto_update.GithubUpdater("JayFromProgramming", "QBT_inhibitor",
                                                 self.update_restart, self.on_new_version)
        asyncio.get_event_loop().create_task(self.updater.run())

    def _task_done(self, task):
        if not self.stop:
            logging.info(f"Task {task.get_name()} failed, restarting")
            task.cancel()
            self.tasks.remove(task)
            if task.get_name() == "plex_detector":
                logging.info(f"Restarting plexDetector")
                # Remove any PlexInhibitor from the list of sources
                self.inhibit_sources.remove_by_type(PlexInhibitor)
                plex_source = PlexInhibitor()
                plex = PlexDetector(self.plex_url, self.plex_token, plex_source)
                self.inhibit_sources.append(plex_source)
                self.tasks.append(asyncio.get_event_loop().create_task(plex.run(), name="plex_detector"))
            elif task.get_name() == "api_server":
                logging.info(f"Restarting webapi")
                # Remove any APIInhibitor from the list of sources
                self.inhibit_sources.remove_by_type(APIInhibitor)
                webapi_source = APIInhibitor()
                webapi_source.version = self.updater.get_installed_version()
                webapi_source.service_restart_method = self.update_restart
                webapi = WebAPI(self.api_ip, 47675, 47676, webapi_source)
                self.inhibit_sources.append(webapi_source)
                self.tasks.append(asyncio.get_event_loop().create_task(webapi.run(), name="api_server"))
            elif task.get_name() == "net_detector":
                logging.info(f"Restarting net_detector")
                # Remove any NetInhibitor from the list of sources
                self.inhibit_sources.remove_by_type(NetInhibitor)
                net_source = NetInhibitor()
                net = NetDetector("Celery", 0.5, net_source)
                self.inhibit_sources.append(net_source)
                self.tasks.append(asyncio.get_event_loop().create_task(net.run(), name="net_detector"))
        else:
            logging.info(f"Task {task.get_name()} failed, but we are stopping, so not restarting")

    async def __aenter__(self):
        """This is where the real init action is"""
        logging.info(f"Initializing qbtInhibitor, connecting to qbittorrent as {self.qbt_username}")
        self._qbt_login()
        logging.info(f"Connected to qbittorrent as {self.qbt_username}, starting plexDetector")
        plex_source = PlexInhibitor()
        plex = PlexDetector(self.plex_url, self.plex_token, plex_source)
        self.inhibit_sources.append(plex_source)
        self.tasks.append(asyncio.get_event_loop().create_task(plex.run(), name="plex_detector"))

        logging.info(f"Starting webapi tasks")
        webapi_source = APIInhibitor()
        webapi_source.version = self.updater.get_installed_version()
        webapi_source.service_restart_method = self.update_restart
        webapi = WebAPI(self.api_ip, 47675, 47676, webapi_source)
        self.webapi = webapi
        self.inhibit_sources.append(webapi_source)
        self.tasks.append(asyncio.get_event_loop().create_task(webapi.run(), name="api_server"))

        logging.info(f"Starting net_detector")
        net_source = NetInhibitor()
        net = NetDetector("Celery", 0.5, net_source)
        self.inhibit_sources.append(net_source)
        self.tasks.append(asyncio.get_event_loop().create_task(net.run(), name="net_detector"))

        for task in self.tasks:  # This is to make sure that we get exceptions in the tasks if they fail
            task.add_done_callback(self._task_done)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.stop = True
        logging.info(f"Exiting qbtInhibitor, logging out of qbittorrent")
        self.qbt.logout()
        logging.info(f"Logged out of qbittorrent, stopping all tasks")
        for source in self.inhibit_sources:
            source.shutdown = True
        logging.info(f"Stopped all tasks, waiting for them to stop")
        await asyncio.sleep(5)
        await asyncio.gather(*self.tasks, return_exceptions=True)
        return self

    def _qbt_login(self):
        try:
            self.qbt.login(self.qbt_username, self.qbt_password)
            self.qbt_connected = True
        except Exception as e:
            logging.error(f"Failed to login to qbittorrent: {e}")
            self.qbt_connected = False

    def _set_rate_limit(self, rate_limit: bool):
        if self.qbt.alternative_speed_status != rate_limit:
            self.qbt.toggle_alternative_speed()

    def _inhibit(self, source: InhibitSource, inhibit: bool):
        pass

    async def on_new_version(self, newest, current):
        """Called when a new version is available"""
        # Check to make sure we are not currently inhibiting
        logging.info(f"New version available, asking user if they want to update")
        await self.webapi.on_update_available(newest, current)

    async def start_update(self):
        """Starts the update process, called by the webapi"""
        logging.info(f"Starting update, allowing 60 seconds so the user can cancel")
        if not self.inhibiting:
            # Start a 1-minute timer to alert users over the api that an updating is going to be installed
            update_time = datetime.datetime.now() + datetime.timedelta(minutes=1)
            while datetime.datetime.now() < update_time:
                if self.stop or self.inhibiting:
                    logging.info("Update cancelled")
                    self.inhibit_sources.update_state(message=f"Update cancelled")
                    break
                await asyncio.sleep(1)
                self.inhibit_sources.update_state(
                    message=f"Updating in {(update_time - datetime.datetime.now()).seconds} seconds")
            if not self.stop and not self.inhibiting:
                logging.info("Update started")
                self.inhibit_sources.update_state(message="Updating...")
                await self.updater.preform_update()

    async def update_restart(self):
        """Called when the updater has finished updating"""
        logging.info("Update finished, restarting")
        self.inhibit_sources.update_state(message="Restarting...")
        await asyncio.sleep(5)
        self.stop = True

    async def run(self):
        while not self.stop:
            logging.debug(f"Checking if we need to inhibit")
            if not self.qbt_connected:
                logging.warning("qbittorrent is not connected, trying to connect")
                self._qbt_login()
            else:
                logging.debug("qbittorrent is connected")

            should_inhibit = False
            overridden = False
            sources = []

            try:
                logging.debug("Checking if we are still connected to qbt")
                _ = self.qbt.global_download_limit
            except Exception as e:
                logging.error(f"Failed to check if we are still connected to qbt: {e}")
                self.qbt_connected = False

            for source in self.inhibit_sources:
                if source.is_override:
                    should_inhibit = source.should_inhibit
                    # sources.append(source)
                    sources = [str(source)]
                    overridden = True
                    break
                else:
                    if source.should_inhibit:
                        should_inhibit = True
                        sources.append(str(source))

            if should_inhibit:
                if sources != self.last_inhibit_sources:
                    self.inhibit_sources.update_state(inhibiting=True, inhibited_by=sources, overridden=overridden)
                if not self.inhibiting:
                    logging.info(f"Inhibiting qbittorrent because of {sources}")
                    self.inhibiting = True
                    self._set_rate_limit(True)
            else:
                if self.inhibiting:
                    self.inhibit_sources.update_state(inhibiting=False, inhibited_by=sources, overridden=overridden)
                    logging.info(f"No longer inhibiting qbittorrent")
                    self.inhibiting = False
                    self._set_rate_limit(False)
            self.last_inhibit_sources = sources
            try:
                self.inhibit_sources.silent_update_state(
                    qbt_connection=self.qbt_connected, plex_connection=
                    self.inhibit_sources.get_by_type(PlexInhibitor).connected_to_plex)
            except Exception as e:
                logging.error(f"Failed to update inhibit sources: {e}")
            await asyncio.sleep(5)


async def main():
    with open("config.json") as config_file:
        config = json.load(config_file)
    async with qbtInhibitor(config['qbt_url'], config['qbt_user'],
                            config['qbt_password'], config['plex_url'], config['plex_token'],
                            config['api_ip']) as inhibitor:
        await inhibitor.run()


asyncio.get_event_loop().run_until_complete(main())
