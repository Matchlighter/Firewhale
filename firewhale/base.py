
import json
from dataclasses import dataclass, field
from typing import Any
from nftables import Nftables

from .nf import *

nft = Nftables()
nft.set_json_output(True)

TABLE_FILTER = "filter"
FIREWHALE_CHAIN = { "family": "ip", "table": TABLE_FILTER, "name": "firewhale" }
DOCKER_USER_CHAIN = { "family": "ip", "table": TABLE_FILTER, "name": "DOCKER-USER" }
ACK_IPS_SET = "firewhale-ack_ips"

@dataclass
class ContainerChainSpec:
    name: str
    rel_addr: str
    map_key: Any = field(kw_only=True, default=None)

    @property
    def config_entry(self) -> str:
        return self.name

    @property
    def map_name(self) -> str:
        return f"firewhale-{self.name}"

    def __post_init__(self):
        if not self.map_key:
            self.map_key = {
                "payload": {
                    "protocol": "ip",
                    "field": self.rel_addr,
                }
            }


CONTAINER_CHAIN_SPECS = [
    ContainerChainSpec("outbound", "daddr"),
    ContainerChainSpec("inbound", "saddr"),
]

firewhaleJumpRule = rule_for_chain(DOCKER_USER_CHAIN, {
    "comment": "Jump to Firewhale Chain",
    "expr": [
        { "jump": { "target": FIREWHALE_CHAIN["name"] } }
    ],
})

CONTAINER_JUMP_RULES = [
    rule_for_chain(FIREWHALE_CHAIN, {
        "comment": f"Jump to container {cdef.name.capitalize()} Chain",
        "expr": [
            {
                "vmap": {
                    "key": cdef.map_key,
                    "data": f"@{cdef.map_name}",
                }
            }
        ],
    }) for cdef in CONTAINER_CHAIN_SPECS
]

allowEstablishedRule = rule_for_chain(FIREWHALE_CHAIN, {
    "comment": "Allow Established Connections",
    "expr": [
        {
            "match": {
                "op": "in",
                "left": {
                    "ct": {
                        "key": "state"
                    }
                },
                "right": [
                    "established",
                    "related"
                ]
            }
        },
        { "counter": None },
        { "return": None },
    ]
})

# DROP if Internal and not in ACK_IPS_SET
# CONTINUE if External or in ACK_IPS_SET
# srcContainerSetupRule = rule_for_chain(FIREWHALE_CHAIN, {
#     "expr": [
#         { "match": {
#             "op": "!=",
#             "left": {
#                 "payload": {
#                     "protocol": "ip",
#                     "field": "saddr",
#                 }
#             },
#             "right": f"@{ACK_IPS_SET}",
#         }},
#         { "drop": {} },
#     ]
# })

def initialize_core_chains():
    for chain in list_table_chains("ip", "filter"):
        if chain["name"] == "DOCKER-USER":
            docker_chain = chain
            break
    else:
        raise RuntimeError("DOCKER-USER Chain not found")

    nfc("add table ip filter")

    chain_maps = [
        {
            "family": "ip",
            "table": "filter",
            "name": cdef.map_name,
            "type": "ipv4_addr",
            "map": "verdict",
        } for cdef in CONTAINER_CHAIN_SPECS
    ]

    nfc([ { "add": { "map": map } } for map in chain_maps ])

    nfc([
        { "add": { "chain": FIREWHALE_CHAIN }},
        { "flush": { "chain": FIREWHALE_CHAIN }},
        { "add": { "rule": allowEstablishedRule }},
        *({ "add": { "rule": rule }} for rule in CONTAINER_JUMP_RULES),
    ])

    sync_chain_rules(docker_chain, [
        firewhaleJumpRule,
    ], tag="[firewhale]")

def full_cleanup():
    # TODO Ignore errors and continue cleaning

    # Remove the Firewhale Rules from the DOCKER-USER chain
    removeTaggedRulesFromChain(DOCKER_USER_CHAIN, "[firewhale]")

    # Clear and Delete the Firewhale chain
    nfc([
        { "flush": { "chain": FIREWHALE_CHAIN } },
        { "delete": { "chain": FIREWHALE_CHAIN } },
    ])

    # Clear and Delete the Container chain maps
    chain_maps = [{ "family": "ip", "table": "filter", "name": cdef.map_name } for cdef in CONTAINER_CHAIN_SPECS]
    nfc([
        *({ "flush": { "map": m } } for m in chain_maps ),
        *({ "delete": { "map": m } } for m in chain_maps ),
    ])

    # Clear and Delete the Container chains
    container_chains = [ch for ch in list_table_chains("ip", "filter") if ch["name"].startswith("firewhale-container-")]
    nfc([
        *( { "flush": { "chain": chain } } for chain in container_chains ),
        *( { "delete": { "chain": chain } } for chain in container_chains ),
    ])
