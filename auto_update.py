import asyncio
import logging
import os
import zipfile

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

    def __init__(self, owner: str, repo: str, restart_callback, on_update_available_callback=None):
        self.repo = repo
        self.owner = owner
        self.restart_callback = restart_callback
        self.on_update_available_callback = on_update_available_callback
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

    async def make_recovery_shell_script(self):
        """Creates a shell script that can be used to restore the old version"""
        if not self.new_version_available:
            logging.info("No new version available")
            return
        logging.info(f"Creating recovery shell script")
        with open("recovery.sh", "w") as f:
            f.write("#!/bin/bash\n")  # Made by Copilot so it likely won't work
            f.write(f"echo 'Restoring old version'\n")
            f.write(f"mv old_version.zip new_version\n")
            f.write(f"mv new_version.zip old_version.zip\n")
            f.write(f"mv old_version old_version.zip\n")
            f.write(f"mv new_version old_version\n")
            f.write(f"echo 'Restored old version'\n")
        os.chmod("recovery.sh", 0o755)
        logging.info("Recovery shell script created")

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

        # Zip the current version as a backup
        with zipfile.ZipFile("old_version.zip", "w") as f:
            for root, dirs, files in os.walk("."):
                for file in files:
                    f.write(os.path.join(root, file))

        await self.make_recovery_shell_script()  # Create recovery script

        # Replace the current version with the new version
        logging.info("Extracting new version")
        with zipfile.ZipFile("new_version.zip", "r") as zip_ref:
            zip_ref.extractall()
        logging.info("New version extracted")
        # Replace the current version with the new version
        import shutil
        shutil.move("new_version", ".")
        logging.info("New version installed")
        with open("version.txt", "w") as f:
            f.write(release["tag_name"])
        # Delete the zip file
        os.remove("new_version.zip")
        logging.info("New version zip file deleted")
        # Restart the program
        logging.info("Calling restart callback")
