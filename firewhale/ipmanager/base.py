from typing import Dict, Set

from ..nf import nfc
from ..rule import nft_service_set_name
from ..util import BiMultiMap, MultiMap


class IPSetManager:
    instance: "IPSetManager" = None

    def __init__(self) -> None:
        # Service <-> Container
        self.service_subscriptions: BiMultiMap[str, str] = BiMultiMap()
        self.ip_service_cache: Dict[str, str] = {}

    def close(self):
        pass

    # === Service IP Publishing ===

    def add_service_ip(self, service: str, ip: str, cid: str):
        raise NotImplementedError()

    def del_service_ip(self, service: str, ip: str, cid: str):
        raise NotImplementedError()

    def del_container_ips(self, cid: str):
        raise NotImplementedError()

    def list_container_ips(self, cid: str) -> Set[str]:
        raise NotImplementedError()

    def del_unknown_ips(self):
        """ Clean up IPs that are registered to this host, but shouldn't be """
        raise NotImplementedError()

    # === Service Subscription ===

    def list_service_ips(self, service: str) -> Set[str]:
        raise NotImplementedError()

    def subscribe_service(self, service: str, cid: str):
        """ Returns True if the Service was not already subscribed """
        if self.service_subscriptions.add(service, cid):
            nfc({ "add": { "set": {
                **self._service_set(service),
                "type": "ipv4_addr",
                "elem": list(self.list_service_ips(service)),
            }}})
            return True

    def unsubscribe_service(self, service: str, cid: str):
        """ Returns True if the service has no remaining Subscribers """
        if self.service_subscriptions.remove(service, cid):
            nfc({ "delete": { "set": {
                **self._service_set(service),
            }}})
            return True

    def unsubscribe_all_services(self, cid: str):
        if not self.service_subscriptions.has_value(cid):
            return

        services = self.service_subscriptions.get_by_value(cid)
        for svc in services:
            self.unsubscribe_service(svc, cid)

    def _update_ip_service(self, service: str, ip: str):
        if not self.service_subscriptions.has_key(service): return

        # Remove the IP from the old service (if applicable)
        if ip in self.ip_service_cache:
            old_service = self.ip_service_cache[ip]
            if old_service != service:
                nfc({ "delete": { "set": {
                    **self._service_set(service),
                }}})

        # Add the IP to the new service
        if service:
            self.ip_service_cache[ip] = service
            nfc({ "add": { "element": {
                **self._service_set(service),
                "elem": ip,
            }}})

    # === Helpers ===

    def _service_set(self, service: str):
        return {
            "family": "ip",
            "table": "filter",
            "name": nft_service_set_name(service),
        }

    @property
    def node_id(self) -> str:
        return "TODO"
