
import os
from threading import Thread

REDIS_URL = "redis://redis:6379/0"
if "REDIS_URL" in os.environ:
    REDIS_URL = os.environ["REDIS_URL"]

def is_in_swarm():
    import docker
    return docker.from_env().info().get("Swarm", {}).get("LocalNodeState") == "active"

def watch_docker_events_thread():
    pass

def full_sync():
#  - initialize_core_chains()
#  - List Docker containers and apply_rules() for each
#  - cleanup_unknown_containers()
    pass # TODO

def serve_nfagent():
    pass

def process_docker_events(events):
    for event in events:
        pass

def serve(swarm=None, redis=None):
    import docker
    docker_client = docker.from_env()

    if swarm is None:
        swarm = is_in_swarm()

    if (redis is None and swarm) or redis is True:
        redis = REDIS_URL

    # If in Swarm or Redis was manually asked for, Connect to Redis and create an RSM
    rsm = None
    if redis:
        import redis
        from .watcher import RedisSubscriptionManager
        r = redis.from_url(redis)
        rsm = RedisSubscriptionManager(r)

    # If in Swarm, create a Unix Socket at /shared/firewhale-nfagent
    #   Or watch for this file to be created and connect to it?
    #   Either way, full_sync() should be called
    if swarm:
        pass # TODO
        # TODO Wait here for initial connection?

    # Subscribe to Docker Container events `create` and `destroy` events
    #   If Redis, also publish events to Redis
    #   Call apply_rules() on create, destroy_rules() on destroy
    events_handle = docker_client.events(
        decode=True,
        filters={
            "type": ["container"],
            "event": ["create", "destroy"],
        }
    )
    event_thread = Thread(target=process_docker_events, args=(events_handle,))
    event_thread.start()

    # If not InSwarm, call full_sync() now (otherwise wait for the NFAgent to connect)
    # TODO

    # TODO Event Loop

    events_handle.close()
    if rsm: rsm.close()

    pass
