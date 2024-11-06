from typing import Dict, Set

from ..util import MultiMap
from .base import IPSetManager


class LocalSubscriptionManager(IPSetManager):
    def __init__(self) -> None:
        super().__init__()

        self.service_published_ips = MultiMap[str, str]()
        self.ip_to_service: Dict[str, str] = {}
        self.ip_to_container: Dict[str, str] = {}

    def add_service_ip(self, service: str, ip: str, cid: str):
        needs_update = ip not in self.ip_to_service or self.ip_to_service.get(ip) != service

        self.ip_to_service[ip] = service
        self.ip_to_container[ip] = cid
        self.service_published_ips.add(service, ip)

        if needs_update:
            self._update_ip_service(service, ip)

    def del_service_ip(self, service: str, ip: str, cid: str):
        if ip in self.ip_to_container and self.ip_to_container[ip] == cid:
            del self.ip_to_service[ip]
            del self.ip_to_container[ip]
            self.service_published_ips.remove(service, ip)

            self._update_ip_service(None, ip)

    def del_container_ips(self, cid: str):
        for ip in self.list_container_ips(cid):
            self.del_service_ip(self.ip_to_service[ip], ip, cid)

    def list_container_ips(self, cid: str) -> Set[str]:
        return [ip for ip, c in self.ip_to_container.items() if c == cid]

    def del_unknown_ips(self):
        pass # TODO Remove any IPs if they aren't associated with a container. May not be needed on the local manager.

    def list_service_ips(self, service: str) -> Set[str]:
        return list(self.service_published_ips[service])
