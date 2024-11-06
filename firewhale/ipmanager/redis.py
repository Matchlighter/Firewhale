
import docker
import docker.models.containers
import redis
from typing import Dict, Set

from ..nf import nfc
from ..rule import nft_service_set_name
from ..util import BiMultiMap, MultiMap
from .base import IPSetManager

class RedisSubscriptionManager(IPSetManager):
    def __init__(self, r) -> None:
        super().__init__()

        self.redis: redis.Redis = r

        # TODO Make this not every container boot?
        from importlib import resources as impresources
        inp_file = impresources.files("firewhale") / 'redis' / 'ips.lua'
        with inp_file.open('r') as f:
            r.function_load(f.read(), True)

        self.pubsub = self.redis.pubsub(ignore_subscribe_messages=True)

        # TODO On reconnect:
        #  - add_service_ip() for all local containers
        #  - del_unknown_ips()
        # r.connection.register_connect_callback

        print("Firewhale is subscribed to Swarm events via Redis")
        self.thread = self.pubsub.run_in_thread(sleep_time=0.1)

    def close(self):
        self.thread.stop()
        self.thread.join()

    # === Service IP Publishing ===

    def add_service_ip(self, service: str, ip: str, cid: str):
        return bool(self.redis.fcall("set_ip", 1, ip, service, cid, self.node_id))

    def del_service_ip(self, service: str, ip: str, cid: str):
        self.redis.fcall("rm_ip", 1, ip, "container", cid)

    def del_container_ips(self, cid: str):
        # print(set(self.redis.smembers(f"container:{cid}:ips")))
        self.redis.fcall("rm_ips_by", 1, cid, "container")

    def list_container_ips(self, cid: str) -> Set[str]:
        return set(self.redis.smembers(f"container:{cid}:ips"))

    def del_unknown_ips(self):
        redis_state = self.redis.smembers(f"node:{self.node_id}:ips")

        from ..container import Container
        local_containers = set(Container(c).id for c in docker.from_env().containers.list(all=True))

        for ip in redis_state:
            state = self.redis.hgetall(f"ip:{ip}")
            if state and state["node_id"] == self.node_id:
                if state["container"] not in local_containers:
                    self.del_service_ip(state["service"], ip, state["container"])
            else:
                self.redis.srem(f"node:{self.node_id}:ips", ip)

    # === Service Subscription ===

    def list_service_ips(self, service: str) -> Set[str]:
        return self.redis.smembers(f"service:{service}:ips")

    def subscribe_service(self, service: str, cid: str):
        if super().subscribe_service(service, cid):
            self.pubsub.subscribe(**{f"service:{service}": self._handle_service_message})

    def unsubscribe_service(self, service: str, cid: str):
        if super().unsubscribe_service(service, cid):
            self.pubsub.unsubscribe(f"service:{service}")

    def _handle_service_message(self, msg):
        # {'channel': b'my-channel', 'data': b'my data', 'pattern': None, 'type': 'message'}
        channel = msg["channel"].decode("utf-8")
        ip = msg["data"].decode("utf-8")

        state = self.redis.hgetall(f"ip:{ip}")
        if state:
            self._update_ip_service(state["service"], ip)
        else:
            self._update_ip_service(None, ip)
