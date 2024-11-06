
import docker
import docker.models
import docker.models.containers

import yaml
from functools import cached_property

from .nf import *
from .base import TABLE_FILTER, CONTAINER_CHAIN_SPECS
from .rule import make_nft_rule, normalize_rule
from .ipmanager import IPSetManager
from .util import protected


class Container:
    def __init__(self, container_id: str | docker.models.containers.Container) -> None:
        if isinstance(container_id, docker.models.containers.Container):
            self.docker_container = container_id
            container_id = container_id.id

        self.container_id = container_id

    def handle_event(self, event: str):
        if event == "create":
            self.apply_rules()
            self.publish_ips()
        elif event == "die":
            self.destroy_rules()
            self.unpublish_ips()

    def publish_ips(self):
        if not self.firewhale_config.get("publish_ips", True):
            return

        docker_nets = self.docker_container.attrs["NetworkSettings"]["Networks"]
        for net_name, net_cfg in docker_nets.items():
            service = f"{self.service_name}.{net_name}"
            self.service_manager.add_service_ip(service, net_cfg["IPAddress"], self.id)

    def unpublish_ips(self):
        self.service_manager.del_container_ips(self.id)

    @protected("Failed to apply rules")
    def apply_rules(self):
        if not self.firewhale_enabled(): return

        if "host" in self.docker_container.attrs["NetworkSettings"]["Networks"]:
            raise ValueError("Container is running in host network mode")

        print(f"Applying rules for container {self.id} ({self.service_name})")

        addrs = self.container_ips()
        watched_services = set()
        commands = []

        for cdef in CONTAINER_CHAIN_SPECS:
            cname = f"{self.chain_prefix}-{cdef.name}"

            nfchain = {
                "family": "ip",
                "table": TABLE_FILTER,
                "name": cname,
            }

            commands.extend([
                # Create Container-specific Chains
                { "add": { "chain": nfchain }},
                { "flush": { "chain": nfchain }},

                # Add Chains to Maps
                { "add": { "element": {
                    "family": "ip",
                    "table": TABLE_FILTER,
                    "name": cdef.map_name,
                    "elem": [
                        [ addr, { "jump": { "target": cname } } ] for addr in addrs
                    ],
                }}}
            ])

            cfg_rules = self.firewhale_config.get(cdef.config_entry, [])
            if isinstance(cfg_rules, str):
                cfg_rules = [cfg_rules]
            norm_rules = [normalize_rule(rule) for rule in cfg_rules]

            nft_rules = [
                make_nft_rule(
                    rule, self.docker_container,
                    addr_type=cdef.rel_addr,
                    chain=nfchain,
                    force_counter=False,
                    referenced_services=watched_services,
                ) for rule in norm_rules
            ]

            # Add the default drop rule
            nft_rules.append(rule_for_chain(nfchain, {
                "expr": [
                    { "drop": None },
                ],
            }))

            for nfr in nft_rules:
                commands.append({ "add": { "rule": nfr } })

        for svc in watched_services:
            self.service_manager.subscribe_service(svc, self.id)

        nfc(commands)

    @protected("Failed to destroy rules")
    def destroy_rules(self):
        # if not self.firewhale_enabled(): return # Not available after container is destroyed

        commands = []

        # TODO Make this more efficient rather than listing all chains
        cont_chains = [ch for ch in list_table_chains("ip", "filter") if ch["name"].startswith(self.chain_prefix)]

        if cont_chains:
            print(f"Removing rules for container {self.id}")

            addrs = self.service_manager.list_container_ips(self.id)
            for cdef in CONTAINER_CHAIN_SPECS:
                # Remove Container-specific Chains from Maps
                commands.append({ "delete": { "element": {
                    "family": "ip",
                    "table": TABLE_FILTER,
                    "name": cdef.map_name,
                    "elem": addrs,
                }}})

            # Remove Container-specific Chains
            for chain in cont_chains:
                # Remove all Rules from the Chain
                commands.append({ "flush": { "chain": chain }})
                # Delete the Chain
                commands.append({ "delete": { "chain": chain }})

            nfc(commands)

        self.service_manager.unsubscribe_all_services(self.id)

    def firewhale_enabled(self):
        return self.firewhale_config.get("enabled", False)

    def container_ips(self):
        return [
            net["IPAddress"] for net in self.docker_container.attrs["NetworkSettings"]["Networks"].values()
        ]

    @property
    def service_manager(self):
        return IPSetManager.instance

    @cached_property
    def service_name(self):
        for k in ["firewhale.service_name", "com.docker.swarm.service.name", "com.docker.compose.service"]:
            if k in self.docker_container.labels:
                return self.docker_container.labels[k]
        return self.docker_container.attrs["Name"].lstrip("/")

    @cached_property
    def docker_container(self):
        return docker.from_env().containers.get(self.container_id)

    @cached_property
    def firewhale_config(self):
        labels = self.docker_container.labels
        firewhale_keys = {}
        for lbl, data in labels.items():
            if lbl.startswith("firewhale."):
                firewhale_keys[lbl.split(".", 1)[1]] = yaml.parse(data)
        return firewhale_keys

    @property
    def id(self):
        return self.container_id[0:16]

    @property
    def chain_prefix(self):
        return f"firewhale-container-{self.id}"

def sync_all_containers(rules = True, ips = True):
    """ Applies NFTables Rules for all Containers """
    active_containers = [Container(c) for c in docker.from_env().containers.list(
        all=True,
    )]
    for container in active_containers:
        if rules: container.apply_rules()
        if ips: container.publish_ips()

def cleanup_unknown_containers():
    """ Cleans up NFTables Rules, Chains and Maps for Containers that no longer exist """
    MAPS_REMOVE_BY_IP = True

    active_containers = [Container(c) for c in docker.from_env().containers.list(
        all=True, filters={ "label": "firewhale.enabled=true" },
    )]

    if MAPS_REMOVE_BY_IP:
        mapped_ips = set(ip for ip, v in get_map_elements("ip", "filter", CONTAINER_CHAIN_SPECS[0].map_name).items())
        running_ips = set(ip for c in active_containers for ip in c.container_ips())
        dead_ips = mapped_ips - running_ips
        if dead_ips:
            for cdef in CONTAINER_CHAIN_SPECS:
                nfc({ "delete": { "element": {
                    "family": "ip",
                    "table": TABLE_FILTER,
                    "name": cdef.map_name,
                    "elem": list(dead_ips),
                }}})

    else:
        map_cache = None
        def find_container_ips(cid):
            nonlocal map_cache
            if not map_cache:
                map_cache = {}
                by_ip = { k: v["jump"]["target"] for k, v in get_map_elements("ip", "filter", CONTAINER_CHAIN_SPECS[0].map_name).items() }
                by_container_id = {}
                for ip, chain in by_ip.items():
                    cid = chain.split("-")[2]
                    if cid not in by_container_id:
                        by_container_id[cid] = []
                    by_container_id[cid].append(ip)
            return map_cache.get(cid, [])

    running_container_ids = set(c.id for c in active_containers)

    # List Chains with container prefix
    container_chains = [ch for ch in list_table_chains("ip", "filter") if ch["name"].startswith("firewhale-container-")]
    for cchain in container_chains:
        # Extract the container ID
        cid = cchain["name"].split("-")[2]

        # Check if the container exists
        if cid not in running_container_ids:
            if not MAPS_REMOVE_BY_IP:
                # Remove Container-specific Chains from Maps. This is not an ideal approach.
                container_ips = find_container_ips(cid)
                if container_ips:
                    for cdef in CONTAINER_CHAIN_SPECS:
                        nfc({ "delete": { "element": {
                            "family": "ip",
                            "table": TABLE_FILTER,
                            "name": cdef.map_name,
                            "elem": container_ips,
                        }}})

            # Remove all Rules from the Chain
            nfc({ "flush": { "chain": cchain }})
            # Delete the Chain
            nfc({ "delete": { "chain": cchain }})
