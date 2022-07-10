import asyncio
import ctypes
import logging
import json
from asyncio import StreamReader, StreamWriter
import uuid

from helpers import InhibitSource, WebInhibitor, APIInhibitor, APIMessageRX, APIMessageTX

logging.getLogger(__name__).setLevel(logging.DEBUG)

handshake_message = json.dumps({"server": "Test", "type": "handshake"}).encode("utf-8")

""" API connection order:
    1. Client sends a POST request to the server with the handshake message
    2. Server responds with a auth challenge message
    3. Client sends a POST request to the server with the auth challenge response
    4. Server responds with either a success message or a failure message
    5. Client and server enter an asynchronous bidirectional loop to communicate
"""


class WebAPI:

    def __init__(self, address: str, main_port: int, alt_port: int, interface_class: APIInhibitor):
        self.address = address
        self.main_port = main_port
        self.alt_port = alt_port
        self.interface_class = interface_class
        with open("api_config.json") as config_file:
            self.config = json.load(config_file)

        self.refresh_task = asyncio.create_task(self._on_inhibit_state_update(self.interface_class.inhibit_event),
                                                name="WebAPI: Background refresh")
        self.refresh_task.add_done_callback(self._on_refresh_task_done)

        self.connections = {}  # List of connections
        self.connections_lock = asyncio.Lock()  # Lock to prevent concurrent access to the connections list

    def get_source(self) -> InhibitSource:
        return self.interface_class

    async def __aenter__(self):
        """Bind to the address and port, and start listening for connections"""
        logging.info(f"Starting web api server on http://{self.address}:{self.main_port}")
        try:
            self.server = await asyncio.start_server(self._on_connection, self.address, self.main_port)
        except OSError as e:
            try:
                logging.error(f"Failed to start web api server on http://{self.address}:{self.alt_port}\n{e}")
                self.server = await asyncio.start_server(self._on_connection, self.address, self.alt_port)
            except Exception as e:
                logging.error(f"Failed to start web api server on http://{self.address}:{self.alt_port}\n{e}")
                raise e
        logging.info(f"Web api server started on http://{self.address}:{self.main_port}")
        return self.server

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Stop the server"""
        logging.info("Stopping web api server")
        self.server.close()
        await self.server.wait_closed()
        logging.info("Web api server stopped")
        return self

    async def _on_connection(self, reader: StreamReader, writer: StreamWriter):
        """When a new connection is made, add it to the list of connections, and send a handshake message"""
        logging.info(f"New connection from {writer.get_extra_info('peername')}")
        # Set task name for debugging
        asyncio.current_task().set_name(f"WebAPI: {writer.get_extra_info('peername')}")
        wave_message = str(await reader.readuntil(b'\n\r'), 'utf-8')
        # Make sure the wave message isn't coming from a browser
        if "HTTP" in wave_message or "POST" in wave_message:
            writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            await writer.drain()
            writer.close()
            return
        msg = APIMessageRX(wave_message)
        if msg.msg_type == "handshake" or msg.msg_type == "renew":
            conn_uuid = await self._on_new(reader, writer)
        # elif msg.msg_type == "renew":
        #     conn_uuid = await self._on_renew(reader, writer, msg.token)
        else:
            logging.warning(f"Unknown message type {msg.msg_type}")
            writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            await writer.drain()
            writer.close()
            return
        await asyncio.sleep(0.1)  # Wait for the connection to fully establish before refreshing the state
        self.interface_class.inhibit_event.set()  # Signal the interface to update the inhibit state

        # Start listening for messages
        logging.info(f"Starting listener for {conn_uuid}")
        new_task = asyncio.create_task(self._listener(conn_uuid), name="WebAPI: Listener")
        new_task.set_name(f"WebAPI: {conn_uuid}, {writer.get_extra_info('peername')}")

    async def _listener(self, conn_uuid: str):
        """Listen to the assigned client"""
        async with self.connections_lock:  # Acquire lock on the connections list to prevent concurrent access
            conn_data = self.connections[conn_uuid]
        logging.info(f"Listener started for {conn_uuid}")
        reader, writer, lock = conn_data["reader"], conn_data["writer"], conn_data["lock"]
        while not self.interface_class.shutdown:
            try:
                new_message = str(await reader.readuntil(b'\n\r'), 'utf-8')
                msg = APIMessageRX(new_message)
                if msg.msg_type == "command":
                    logging.info(f"Received command {msg}")
                    self.interface_class.should_inhibit = msg.inhibit
                    self.interface_class.overridden = msg.override
                    self.interface_class.inhibit_event.set()

                elif msg.msg_type == "ack":
                    pass
                elif msg.msg_type == "refresh":
                    api_message = APIMessageTX(
                        msg_type="state_update",
                        inhibiting=self.interface_class.inhibiting,
                        inhibited_by=self.interface_class.inhibited_by,
                        overridden=self.interface_class.overridden,
                        qbt_connection=self.interface_class.qbt_connection,
                        plex_connection=self.interface_class.plex_connection,
                        message=self.interface_class.message)
                    writer.write(api_message.encode('utf-8'))
                    logging.debug(f"Acquiring lock for {writer.get_extra_info('peername')}, {lock}")
                    async with lock:
                        await writer.drain()
                else:
                    logging.warning(f"Unknown message type {msg.msg_type}")

                # async with lock:
                #     send = APIMessageTX(
                #         msg_type="ack",
                #         token=msg.token)
                #     writer.write(send.encode('utf-8'))
                #     await writer.drain()
            except EOFError:
                logging.warning(f"Connection from {writer.get_extra_info('peername')} closed, EOF")
                break
            except OSError:
                logging.warning(f"Connection from {writer.get_extra_info('peername')} closed, OSError")
                break
        logging.warning(f"Listener stopped for {conn_uuid}")
        await self._on_disconnect(token=conn_uuid)

    async def _on_new(self, reader: StreamReader, writer: StreamWriter) -> str:
        """Called when a new connection is made"""
        token = uuid.uuid4().hex
        lock = asyncio.Lock()
        async with self.connections_lock:
            self.connections.update({token: {"reader": reader, "writer": writer, "lock": lock}})
        logging.debug(f"Added connection {token} to list from {writer.get_extra_info('peername')}")
        api_message = APIMessageTX(
            msg_type="new_conn",
            token=token)
        async with lock:
            writer.write(api_message.encode('utf-8'))
            await writer.drain()
        logging.info(f"New connection from {writer.get_extra_info('peername')} with token {token}")
        return token

    # async def _on_renew(self, reader: StreamReader, writer: StreamWriter, token: str):
    #     """Called when an existing connection is reestablished"""
    #     async with self.connections_lock:
    #         # Find the connection with the given token
    #         for connection in self.connections:
    #             if connection["token"] == token:
    #                 # Replace the old reader and writer with the new ones
    #                 connection["reader"] = reader
    #                 connection["writer"] = writer
    #                 connection["lock"] = asyncio.Lock()  # Create a new lock for the connection
    #                 connection["lock"].release()  # Release the lock
    #                 logging.debug(f"Renewed connection with token {token}")
    #                 api_message = APIMessageTX(
    #                     msg_type="renew_conn",
    #                     token=token)
    #                 async with connection["lock"]:
    #                     writer.write(api_message.encode('utf-8'))
    #                     await writer.drain()
    #                 return token
    #         logging.warning(f"Could not find connection with token {token}")
    #         await self._on_new(reader, writer)

    async def _on_disconnect(self, token: str):
        """Called when a connection is closed"""
        logging.info(f"Disconnected from {token} with {self.connections[token]['writer'].get_extra_info('peername')}")
        async with self.connections_lock:
            if token in self.connections:
                # Close the reader and writer
                reader, writer = self.connections[token]["reader"], self.connections[token]["writer"]
                reader.feed_eof()
                writer.close()
                del self.connections[token]
                logging.debug(f"Removed connection with token {token}")
            else:
                logging.warning(f"Could not find connection with token {token}")

    async def _on_inhibit_state_update(self, event):
        """When the inhibitor changes state send a message to all connected clients to update the state"""
        while not self.interface_class.shutdown:
            try:
                logging.debug(f"Connection state updator is primed")
                await event.wait()
                logging.info(f"Updating all connections with new inhibit state")

                api_message = APIMessageTX(
                    msg_type="state_update",
                    inhibiting=self.interface_class.inhibiting,
                    inhibited_by=self.interface_class.inhibited_by,
                    overridden=self.interface_class.overridden,
                    qbt_connection=self.interface_class.qbt_connection,
                    plex_connection=self.interface_class.plex_connection,
                    message=self.interface_class.message)

                async with self.connections_lock:  # Acquire lock on the connections list to prevent concurrent access
                    for token, connection in self.connections.items():
                        async with connection["lock"]:
                            try:
                                connection["writer"].write(api_message.encode('utf-8'))
                                await connection["writer"].drain()
                            except OSError:
                                await self._on_disconnect(token)
                                break

            except Exception as e:
                logging.error(f"Error in connection state updator: {e}")
                await asyncio.sleep(1)
            finally:
                event.clear()

    async def run(self):
        try:
            async with self as serv:
                while not self.interface_class.shutdown:
                    await asyncio.sleep(1)
                serv.close()
        except Exception as e:
            logging.error(f"Error in server: {e}")
            raise e

    def _on_refresh_task_done(self):
        logging.info("Refresh task finished")
        pass

    def _on_listener_done(self, task: asyncio.Task, conn_uuid) -> None:
        """Log when the listener exits, and remove the connection"""
        logging.info(f"Listener {task.get_name()} for {conn_uuid} exited")

        self.connections[self.connections.index({"token": conn_uuid})]["lock"].release()
        self.connections[self.connections.index({"token": conn_uuid})] = {
            "token": conn_uuid,
            "reader": None,
            "writer": None,
            "lock": None
        }


