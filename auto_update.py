import asyncio
import logging

import aiohttp
import requests


logging.getLogger(__name__).setLevel(logging.DEBUG)


async def _get_installed_version():
    try:
        with open("version.txt") as version_file:
            return version_file.read().strip()
    except Exception as e:
        logging.error(f"Failed to get installed version: {e}")
        return None


class GithubUpdater:

    def __init__(self, repo):
        self.repo = repo
        self.new_version_available = False

    async def _get_latest_release(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.github.com/repos/{self.repo}/releases/latest") as resp:
                return await resp.json()

    async def run(self):
        while True:
            logging.debug("Checking github for updates")
            latest_release = await self._get_latest_release()
            if latest_release is None:
                logging.error("Failed to get latest release")
                await asyncio.sleep(5)
                continue
            if latest_release["tag_name"] != await _get_installed_version():
                logging.info(f"New version available: {latest_release['tag_name']}")
                self.new_version_available = True
            else:
                self.new_version_available = False
            await asyncio.sleep(30)

    def preform_update(self):
        """Downloads new version and replaces current version"""


