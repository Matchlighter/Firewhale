
import os
import time
from threading import Thread

from .ipmanager.base import IPSetManager
from .nfbackends import nf_backend_store


def is_in_swarm():
    import docker
    return docker.from_env().info().get("Swarm", {}).get("LocalNodeState") == "active"

def full_rule_sync(publish_ips=False):
    if nf_backend_store.connected:
        from .base import initialize_core_chains
        from .container import sync_all_containers, cleanup_unknown_containers

        initialize_core_chains()
        sync_all_containers(ips=publish_ips)
        cleanup_unknown_containers()


def serve_nfagent():
    pass

def serve(nfagent=None, redis_url=None):
    import docker
    docker_client = docker.from_env()

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

    # If in Swarm, create a Unix Socket at /shared/firewhale-nfagent
    #   Or watch for this file to be created and connect to it?
    #   Either way, full_sync() should be called
    # Always create?
    if nfagent:
        pass # TODO
        # TODO Wait here for initial connection?
    # TODO Create NFBackend

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
    def process_docker_events(events):
        from .container import Container

        for event in events:
            try:
                if event["Type"] == "container":
                    ctr = Container(event["id"])
                    ctr.handle_event(event["Action"])
            except Exception as e:
                import traceback
                # TODO Better loggering
                print(f"Error processing event {event}:")
                traceback.print_exc()

    event_thread = Thread(target=process_docker_events, args=(events_handle,))
    print("Firewhale is subscribed to local Docker events")
    event_thread.start()

    try:
        from .container import sync_all_containers
        sync_all_containers(rules=False)

        full_rule_sync()
        while True:
            # TODO Event Loop
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        events_handle.close()
        ipmanager.close()
        event_thread.join()
