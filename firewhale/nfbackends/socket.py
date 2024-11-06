
import json, socket
import threading
import websockets as ws
import os
import time
from websockets.sync.server import unix_serve

from .base import NFTBackend, NftError

class SocketNFTBackend(NFTBackend):
    def __init__(self, socket_path):
        super().__init__()
        self.socket_path = socket_path

        self.socket_lock = threading.Lock()
        self.current_connection: ws.server.ServerConnection = None

        self.ws_server = None
        self.server_thread = None

    def connect(self):
        self.ws_server = unix_serve(self.ws_server_handler, self.socket_path)
        self.server_thread = threading.Thread(target=lambda: self.ws_server.serve_forever(), daemon=True)
        self.server_thread.start()

    def stop(self):
        if self.ws_server is not None:
            os.unlink(self.socket_path)
            self.ws_server.shutdown()
            self.server_thread.join()

    def ws_server_handler(self, sock: ws.server.ServerConnection):
        if self.current_connection is not None:
            print("Already connected - closing previous connection")
            self.current_connection.close()
        self.current_connection = sock

        if self.on_connect is not None:
            self.on_connect()

        print("NFAgent Connected")

        while True:
            try:
                with self.socket_lock:
                    sock.ping()
            except ws.ConnectionClosed:
                print("NFAgent Disconnected")
                break
            time.sleep(10)

    def cmd(self, cmd, *, throw=True):
        if self.current_connection is None:
            raise NftError("Not connected to agent")

        with self.socket_lock:
            self.current_connection.send(json.dumps({
                "cmd": cmd,
                "throw": throw,
            }))

            result = json.loads(self.current_connection.recv(timeout=1))

            if result["status"] == "error":
                raise NftError(result["data"])

            return result["data"]
