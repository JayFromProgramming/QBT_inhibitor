import asyncio
import logging

import aiohttp

logging.getLogger(__name__).setLevel(logging.DEBUG)


async def _get_installed_version():
    try:
        with open("version.txt") as version_file:
            return version_file.read().strip()
    except Exception as e:
        logging.error(f"Failed to get installed version: {e}")
        return "unknown"


class GithubUpdater:

    def __init__(self, owner: str, repo: str):
        self.repo = repo
        self.owner = owner
        self.new_version_available = False

    async def _get_latest_release(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/latest") as resp:
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

    async def preform_update(self):
        """Downloads new version and replaces current version"""
        if not self.new_version_available:
            logging.info("No new version available")
            return
        logging.info(f"Downloading new version: {self.repo}")
        release = await self._get_latest_release()
        # Download the zip file from github and extract it
        async with aiohttp.ClientSession() as session:
            req = await session.get(release["assets"][0]["browser_download_url"])
            with open("new_version.zip", "wb") as f:
                while True:
                    chunk = await req.content.read(1024)
                    if not chunk:
                        break
                    f.write(chunk)
        logging.info("Extracting new version")
        import zipfile
        with zipfile.ZipFile("new_version.zip", "r") as zip_ref:
            zip_ref.extractall()
        logging.info("New version extracted")
        # Replace the current version with the new version
        import shutil
        shutil.move("new_version", ".")
        logging.info("New version installed")

