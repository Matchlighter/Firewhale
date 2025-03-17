
import os
import signal
from threading import Thread
from queue import Queue
from dataclasses import dataclass
from typing import Literal, Any

from .ipmanager.base import IPSetManager
from .nfbackends import nf_backend_store


@dataclass
class QItem:
    type: Literal["docker"] | Literal["nfbackend"] | Literal["stop"]
    data: Any

def is_in_swarm():
    import docker
    return docker.from_env().info().get("Swarm", {}).get("LocalNodeState") == "active"

async def serve_nfagent():
    import json
    import asyncio
    import websockets as ws
    from websockets.asyncio.client import unix_connect

    from .nfbackends.base import NftError
    from .nfbackends.local import LocalNFTBackend

    print("Starting NFAgent and connecting to Firewhale")

    conns: set[ws.client.ClientConnection] = set()

    nfb = LocalNFTBackend()

    do_quit = False
    def handle_exit_signal(self,signum, frame):
        nonlocal do_quit
        for conn in conns:
            conn.close()
        do_quit = True

    signal.signal(signal.SIGINT, handle_exit_signal)
    signal.signal(signal.SIGTERM, handle_exit_signal)

    async def handle_socket(socket: ws.client.ClientConnection):
        while True:
            try:
                message = await socket.recv()
                m = json.loads(message)
                if "nfcmd" in m:
                    try:
                        print(m["nfcmd"])
                        result = nfb.cmd(m["nfcmd"], throw=m.get("throw", True))
                        result = { "status": "ok", "data": result }
                    except NftError as e:
                        result = { "status": "error", "data": str(e) }
                    await socket.send(json.dumps(result))
            except ws.ConnectionClosed as e:
                print("Disconnected from Firewhale", e)
                break
            except Exception as e:
                print("NFAgent Error", e)

    while True:
        try:
            async with unix_connect("/tmp/firewhale/agent/socket") as socket:
                try:
                    print("Connected to Firewhale")
                    conns.add(socket)
                    await handle_socket(socket)
                finally:
                    conns.remove(socket)

            if do_quit:
                break

        except Exception as e:
            print("Error connecting to Firewhale", e)
            await asyncio.sleep(3)


def serve(nfagent=None, redis_url=None):
    import docker
    docker_client = docker.from_env()

    # TODO Convert to asyncio?

    if nfagent is None:
        nfagent = is_in_swarm()

    if (redis_url is None and is_in_swarm()) or redis_url is True:
        redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    if nfagent and redis_url:
        mode = "Swarm (Redis+NFAgent)"
    elif nfagent:
        mode = "Local+NFAgent"
    elif redis_url:
        mode = "Redis"
    else:
        mode = "Local"
    print(f"Starting Firewhale in {mode} mode")

    q = Queue[QItem]()

    # === IPSetManager Setup ===

    # If in Swarm or Redis was manually asked for, Connect to Redis and create an RSM
    ipmanager = None
    if redis_url:
        import redis
        from .ipmanager.redis import RedisSubscriptionManager
        r = redis.from_url(redis_url)
        ipmanager = RedisSubscriptionManager(r)
    else:
        from .ipmanager.local import LocalSubscriptionManager
        ipmanager = LocalSubscriptionManager()

    IPSetManager.instance = ipmanager


    # === NFBackend Setup ===

    if nfagent:
        from .nfbackends.socket import SocketNFTBackend
        nf_backend = SocketNFTBackend("/tmp/firewhale/agent/socket")
        nf_backend_store.set_backend(nf_backend)
    else:
        from .nfbackends.local import LocalNFTBackend
        nf_backend = LocalNFTBackend()
        nf_backend_store.set_backend(nf_backend)

    nf_backend.on_connect = lambda: q.put(QItem("nfbackend", "connected"))

    def handle_nf_connected():
        from .base import initialize_core_chains
        from .container import sync_all_containers, cleanup_unknown_containers

        initialize_core_chains()
        sync_all_containers(ips=False)
        cleanup_unknown_containers()


    # === Docker Event Handling ===

    # Subscribe to Docker Container events `create` and `destroy` events
    #   If Redis, also publish events to Redis
    #   Call apply_rules() on create, destroy_rules() on destroy
    events_handle = docker_client.events(
        decode=True,
        filters={
            "type": ["container"],
            "event": ["create", "die"],
        }
    )

    def process_docker_event(event):
        from .container import Container
        if event["Type"] == "container":
            ctr = Container(event["id"])
            ctr.handle_event(event["Action"])

    def process_docker_events(events):
        for event in events:
            q.put(QItem("docker", event))

    event_thread = Thread(target=process_docker_events, args=(events_handle,))
    print("Firewhale is subscribed to local Docker events")
    event_thread.start()

    def handle_exit_signal(self,signum, frame):
        q.put(QItem("stop", None))
    signal.signal(signal.SIGINT, handle_exit_signal)
    signal.signal(signal.SIGTERM, handle_exit_signal)

    # === Main Program ===

    try:
        from .container import sync_all_containers
        sync_all_containers(rules=False)

        nf_backend.connect()

        while True:
            qitem = q.get()

            try:
                if qitem.type == "docker":
                    process_docker_event(qitem.data)

                elif qitem.type == "nfbackend" and qitem.data == "connected":
                    handle_nf_connected()

                elif qitem.type == "stop":
                    break

            except Exception as e:
                import traceback
                # TODO Better loggering
                print(f"Error:")
                traceback.print_exc()

            q.task_done()

    except KeyboardInterrupt:
        pass
    finally:
        print("Shutting down Firewhale")
        events_handle.close()
        ipmanager.close()
        nf_backend.stop()
        event_thread.join()
