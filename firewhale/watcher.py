
import docker
import docker.models.containers
import redis
from typing import Dict, Set

from .nf import nfc
from .rule import nft_service_set_name

# TODO Local RSM that adds IPs directly to NFT

# class ServiceLink:
    # ip
    # service
    # container_id
    # node_id
    # timestamp

class IPSetManager:
    def notify_change(self, change: Dict):
        pass

    def remove_unknown_ips(self):
        # SELECT * FROM service_links WHERE node_id = $1 AND container_id NOT IN (containers)
        # DELETE FROM service_links WHERE node_id = $1 AND container_id NOT IN (containers)
        # Publish unlink notifications
        pass

    def subscribe_service(self, service: str):
        # Create NFT Set
        # Subscribe
        # SELECT ip FROM service_links WHERE service = $1
        # Fill NFT Set from ^
        pass

    def unsubscribe_service(self, service: str):
        # Unsubscribe
        # Clear and Delete NFT Set
        pass

    def unsubscribe_all_services(self, container_id: str):
        # See Below
        pass

class LocalSubscriptionManager(IPSetManager):
    pass

class RedisSubscriptionManager:
    def __init__(self, r: redis.Redis) -> None:
        self.redis = r
        self.pubsub = self.redis.pubsub()

        # TODO Call add_service_ips/remove_service_ips on reconnect
        # r.connection.register_connect_callback

        self.subscribed_services: Dict[str, Set[str]] = {}
        self.container_services: Dict[str, Set[str]] = {}

        self.thread = self.pubsub.run_in_thread(sleep_time=0.1)

    def close(self):
        self.thread.stop()

    def add_service_ips(self, service: str, container: docker.models.containers.Container):
        for net_name, net_cfg in container.attrs["NetworkSettings"]["Networks"]:
            full_service = f"{service}.{net_name}"
            added = self.redis.sadd(f"{full_service}-ips", net_cfg["IPAddress"])
            # TODO Perhaps use a Hash so each IP can have an owning node
            # TODO Some sort of multi-index store may be more desirable - index on Service and Node
            #   IP - Service - Node ID - Container ID - Timestamp
            #   This way it is easy all IPs for a Service or a Node if we need to remove a node
            # Consider whether a node needs to be active to own an IP
            if added:
                self.redis.publish(f"service:{service}", { "add": net_cfg["IPAddress"] })

    def remove_service_ips(self, service: str, container: docker.models.containers.Container):
        for net_name, net_cfg in container.attrs["NetworkSettings"]["Networks"]:
            full_service = f"{service}.{net_name}"
            removed = self.redis.srem(f"{full_service}-ips", net_cfg["IPAddress"])
            if removed:
                self.redis.publish(f"service:{service}", { "del": net_cfg["IPAddress"] })

    def subscribe_service(self, service: str, cid: str):
        _add_entry(self.container_services, cid, service)
        if _add_entry(self.subscribed_services, service, cid):
            nfc({ "add": { "set": {
                **self._service_set(service),
                "type": "ipv4_addr",
                "elem": self.redis.smembers(f"{service}-ips"),
            }}})
            self.pubsub.subscribe(**{f"service:{service}": self._handle_service_message})

    def unsubscribe_service(self, service: str, cid: str):
        _remove_entry(self.container_services, cid, service)
        if _remove_entry(self.subscribed_services, service, cid):
            self.pubsub.unsubscribe(f"service:{service}")
            nfc({ "delete": { "set": {
                **self._service_set(service),
            }}})

    def unsubscribe_all_services(self, cid: str):
        services = self.container_services.get(cid, [])
        for svc in services:
            self.unsubscribe_service(svc, cid)

    def _handle_service_message(self, msg):
        pass

    def _service_set(self, service: str):
        return {
            "family": "ip",
            "table": "filter",
            "name": nft_service_set_name(service),
        }

def _add_entry(mmap, key: str, value):
    ret = False
    if key not in mmap:
        mmap[key] = set()
        ret = True
    mmap[key].add(value)
    return ret

def _remove_entry(mmap, key: str, value):
    if key not in mmap: return True
    mmap[key].discard(value)
    if len(mmap[key]) == 0:
        del mmap[key]
        return True
    return False
