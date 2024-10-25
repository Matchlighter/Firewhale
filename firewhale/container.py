
import docker
import docker.models
import docker.models.containers

import yaml
from functools import cached_property

from .nf import *
from .base import TABLE_FILTER, CONTAINER_CHAIN_SPECS
from .rule import make_nft_rule, normalize_rule

class Container:
    def __init__(self, dcontainer: docker.models.containers.Container) -> None:
        self.docker_container = dcontainer

    def apply_rules(self):
        if not self.firewhale_enabled(): return

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

        # TODO Subscribe to watched_services

        nfc(commands)

    def destroy_rules(self):
        # TODO Unsubscribe from watched_services

        commands = []

        addrs = self.container_ips()
        for cdef in CONTAINER_CHAIN_SPECS:
            # Remove Container-specific Chains from Maps
            commands.append({ "delete": { "element": {
                "family": "ip",
                "table": TABLE_FILTER,
                "name": cdef.map_name,
                "elem": addrs,
            }}})

        # Remove Container-specific Chains
        cont_chains = [ch for ch in list_table_chains("ip", "filter") if ch["name"].startswith(self.chain_prefix)]
        for chain in cont_chains:
            # Remove all Rules from the Chain
            commands.append({ "flush": { "chain": chain }})
            # Delete the Chain
            commands.append({ "delete": { "chain": chain }})

        nfc(commands)

    def firewhale_enabled(self):
        return self.firewhale_config.get("enabled", False)

    def container_ips(self):
        return [
            net["IPAddress"] for net in self.docker_container.attrs["NetworkSettings"]["Networks"].values()
        ]

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
        return self.docker_container.id[0:16]

    @property
    def chain_prefix(self):
        return f"firewhale-container-{self.id}"

def cleanup_unknown_containers():
    MAPS_REMOVE_BY_IP = True

    running_containers = [Container(c) for c in docker.from_env().containers.list()]
    running_containers = [c for c in running_containers if c.firewhale_enabled()]

    if MAPS_REMOVE_BY_IP:
        mapped_ips = set(ip for ip, v in get_map_elements("ip", "filter", CONTAINER_CHAIN_SPECS[0].map_name).items())
        running_ips = set(ip for c in running_containers for ip in c.container_ips())
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

    running_container_ids = set(c.id for c in running_containers)

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
