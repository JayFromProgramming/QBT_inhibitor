import asyncio
import json
import logging
import os
import pathlib
import traceback
import logging

import aiohttp

installed_dir = os.path.dirname(os.path.realpath(__file__))

logging.getLogger(__name__).setLevel(logging.DEBUG)


def cleanup():
    # Look for the old_version.zip file and delete it and the recovery script
    if os.path.exists("old_version.zip"):
        os.remove("old_version.zip")
    if os.path.exists("recovery.sh"):
        os.remove("recovery.sh")


class GithubUpdater:

    def __init__(self, owner: str, repo: str, restart_callback=None,
                 update_available_callback=None):
        self.repo = repo
        self.owner = owner
        self.restart_callback = restart_callback
        self.on_update_available_callback = update_available_callback
        self.new_version_available = False
        cleanup()

    async def _get_latest_release(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/latest") as resp:
                return await resp.json()

    def _get_installed_version(self):
        try:
            current_script_dir = pathlib.Path(__file__).parent.resolve()
            with open(os.path.join(current_script_dir, "version.txt")) as version_file:
                return version_file.read().strip()
        except Exception as e:
            logging.error(f"Failed to get installed version: {e}")
            return "unknown"

    def version(self):
        """Returns the installed version"""
        return self._get_installed_version()

    async def run(self):
        logging.debug("Starting auto update check")
        while True:
            try:
                logging.debug("Checking github for updates")
                latest_release = await self._get_latest_release()
                if latest_release is None:
                    logging.error("Failed to get latest release")
                    await asyncio.sleep(5)
                    continue

                if "tag_name" not in latest_release:
                    logging.error("No latest release tag found")
                    await asyncio.sleep(5)
                    continue

                if latest_release["tag_name"] != self._get_installed_version():
                    logging.info(f"New version available: {latest_release['tag_name']}")
                    self.new_version_available = True
                    if self.on_update_available_callback is not None:
                        current_version = self._get_installed_version()
                        await self.on_update_available_callback(newest=latest_release["tag_name"],
                                                                current=current_version)
                else:
                    self.new_version_available = False
            except Exception as e:
                logging.error(f"Failed to check for updates: {e}\n{traceback.format_exc()}")
            finally:
                await asyncio.sleep(60)

    async def make_recovery_shell_script(self):
        """Creates a shell script that can be used to restore the old version"""
        if not self.new_version_available:
            logging.debug("No new version available")
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
        """Downloads the latest version and replaces the current version"""
        try:
            # Get release info
            logging.info("Getting latest release")
            latest_release = await self._get_latest_release()

            if latest_release is None:
                logging.error("Failed to get latest release")
                return

            if "tag_name" not in latest_release:
                logging.error("No latest release tag found")
                return

            logging.info("Preforming update... (using gitpull)")
            result = os.popen("git pull").read()
            logging.info(result)
            if result.startswith("Already up to date."):
                logging.info("Already up to date - not updating")
                with open("version.txt", "w") as f:
                    f.write(latest_release["tag_name"])
                return
            elif result == "":
                logging.info("Some unknown git error occurred, not updating")
                return
            logging.info("Updated")
            # Run post update requirement update
            result = os.popen(f"pip install -r requirements.txt").read()
            logging.info(result)
            logging.info("Post update requirement update complete")

            with open("version.txt", "w") as f:
                f.write(latest_release["tag_name"])

            if self.restart_callback is not None:
                await self.restart_callback()
        except Exception as e:
            logging.error(f"Failed to update: {e}\n{traceback.format_exc()}")