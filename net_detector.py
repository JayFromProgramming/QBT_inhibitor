import asyncio
import logging
import traceback

import psutil

from helpers import NetInhibitor

logging.getLogger(__name__).setLevel(logging.DEBUG)


class NetDetector:

    def __init__(self, net_interface: str, threshold: float, interface_class: NetInhibitor):
        self.net_interface = net_interface
        self.threshold = threshold
        self.interface_class = interface_class
        self.interface_class.connected_to_net = True

    # Get the upload stats from the interface
    @staticmethod
    async def get_network_upload(interface_name):
        old_value = psutil.net_io_counters(pernic=True)[interface_name].bytes_sent
        await asyncio.sleep(1)
        new_value = psutil.net_io_counters(pernic=True)[interface_name].bytes_sent
        return new_value - old_value

    # Convert bytes to mbit
    @staticmethod
    def convert_to_mbit(value):
        return value / 1024. / 1024. * 8

    async def run(self):
        logging.info(f"Initializing netDetector, checking {self.net_interface} with threshold {self.threshold} mbit/s")
        while not self.interface_class.shutdown:
            logging.debug("Checking network upload")
            try:
                if self.convert_to_mbit(await self.get_network_upload(self.net_interface)) > self.threshold:
                    self.interface_class.should_inhibit = True
                else:
                    self.interface_class.should_inhibit = False
            except Exception as e:
                logging.error(f"Failed to get network upload: {e}\n{traceback.format_exc()}")
                self.interface_class.connected_to_net = False
            else:
                self.interface_class.connected_to_net = True
            finally:
                await asyncio.sleep(5)
