
from typing import List, Set
import re

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .container import Container

VALID_PROTOCOLS = set(["tcp", "udp"])
ALIASES = {
    "sport": "src_port",
    "dport": "dst_port",
}

def nft_service_set_name(service: str):
    return f"firewhale-service:{service}:ip"

# Rule: { peer, src_port, dst_port, proto, jump }
#   tcp; caddy.caddy; 80; srcport:8000-9000; jump:xyz-chain
def normalize_rule(rule):
    if isinstance(rule, str):
        bits: List[str] = rule.split(";")
        bits = [bit.strip() for bit in bits]
        rule = {}

        # Protocol (Optional)
        if bits[0].lower() in VALID_PROTOCOLS:
            rule["proto"] = bits.pop(0).lower()

        # Peer
        rule["peer"] = bits.pop(0)

        # Ports (Optional)
        if len(bits) and ":" not in bits[0]:
            rule["dst_port"] = bits.pop(0)
        if len(bits) and bits[0].startswith(":"):
            rule["dst_port"] = bits.pop(0)[1:]

        # Key-Value Pairs
        for bit in bits:
            left, right = bit.split(":", 1)
            if not left or not right:
                raise ValueError(f"Invalid key-value pair: {bit}")
            rule[left] = right

    norm_rule = {}
    for key, value in rule.items():
        key = ALIASES.get(key, key)
        norm_rule[key] = value

    return norm_rule

def full_network_name(container: 'Container', net_name: str):
    networks = container.attrs["NetworkSettings"]["Networks"]

    for k in networks.keys():
        if k == net_name: return net_name

    namespace = ""
    for k in ["com.docker.compose.project", "com.docker.stack.namespace"]:
        if k in container.labels:
            namespace = container.labels[k]
            break

    for k in networks.keys():
        if k == f"{namespace}_{net_name}":
            return k

    return net_name

def make_nft_rule(rule, container: 'Container', *,
    chain=None,
    addr_type: str,
    force_counter: bool = False,
    referenced_services: Set[str] = set(),
):
    nfexprs = []

    nfexprs.append({ "match": {
        "op": "==",
        "left": { "payload": { "protocol": "ip", "field": "protocol" } },
        "right": rule["proto"] if "proto" in rule else { "set": ["tcp", "udp"] },
    }})

    if "peer" in rule:
        peer = rule["peer"]

        m = {
            "op": "==",
            "left": { "payload": { "protocol": "ip", "field": addr_type } },
        }

        # TODO Support IPv6

        def build_host_matchers():
            nonlocal m, peer

            if peer == "*":
                m = None
                return

            invert = False

            if peer.startswith("!"):
                invert = True
                peer = peer[1:]

            # Internet
            if peer == "internet":
                invert = not invert
                peer = "local-networks"

            if invert:
                m["op"] = "!="

            # Local Networks
            if peer == "local-networks":
                nets = ['10.0.0.0/8', '192.168.0.0/16', '172.16.0.0/12']
                for n in nets:
                    addr, prefix = n.split("/")
                    nfexprs.append({ "match": {
                        **m,
                        "right": { "prefix": { "addr": addr, "len": int(prefix) } }
                    } })
                return

            # Network
            match = re.match(r"^\*\.(\w+)$", peer)
            if match:
                net_name, = match.groups()
                net_name = full_network_name(container, net_name)
                nets = container.attrs["NetworkSettings"]["Networks"]
                if net_name not in nets:
                    raise ValueError(f"Network {net_name} not found")
                net = net[net_name]
                m["right"] = { "prefix": { "addr": net["IPAddress"], "len": net["IPPrefixLen"] } }

                nfexprs.append({ "match": m })
                return

            # Service (Service Name in Swarm/Compose - otherwise Container Name)
            match = re.match(r"^(?:(\w+):)?(\w+)\.(\w+)$", peer)
            if match:
                ns, service_name, net_name = match.groups()

                if not ns: ns = container.stack_namespace
                if ns:
                    service_name = f"{ns}_{service_name}"

                net_name = full_network_name(container, net_name)
                peer = f"{service_name}.{net_name}"
                referenced_services.add(peer)
                set_name = nft_service_set_name(peer)
                m["right"] = f"@{set_name}"

                nfexprs.append({ "match": m })
                return

            # IP/CIDR
            match = re.match(r"^(\d+\.\d+\.\d+\.\d+)(?:\/(\d+))$", peer)
            if match:
                ip, prefix = match.groups()
                if prefix:
                    m["right"] = { "prefix": { "addr": ip, "len": int(prefix) } }
                else:
                    m["right"] = ip

                nfexprs.append({ "match": m })
                return

            # IP Range
            match = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s*\-\s*(\d+\.\d+\.\d+\.\d+)$", peer)
            if match:
                m["right"] = { "range": peer.split("-") }

                nfexprs.append({ "match": m })
                return

        build_host_matchers()

    if "src_port" in rule:
        nfexprs.append({ "match": {
            "op": "==",
            "left": { "payload": { "protocol": "tcp", "field": "sport" } },
            "right": parse_port(rule["src_port"]),
        }})

    if "dst_port" in rule:
        nfexprs.append({ "match": {
            "op": "==",
            "left": { "payload": { "protocol": "tcp", "field": "sport" } },
            "right": parse_port(rule["dst_port"]),
        }})

    if force_counter or ("counter" in rule and rule["counter"]):
        nfexprs.append({ "counter": None })

    if "log_prefix" in rule:
        nfexprs.append({ "log": { "prefix": rule["log_prefix"], "level": "info" } })

    if "chain" in rule:
        nfexprs.append({ "goto": { "target": rule["chain"] } })
    else:
        # "Accept" Rules should actually be "Return" Rules)
        nfexprs.append({ "return": None })

    rule = {
        "expr": nfexprs,
    }

    if chain:
        rule["family"] = chain["family"]
        rule["table"] = chain["table"]
        rule["chain"] = chain["name"]

    if "comment" in rule:
        rule["comment"] = rule["comment"]

    return rule

def parse_port(port):
    if port.isdigit():
        return int(port)
    elif re.match(r"^\d+\s*\-\s*\d+$", port):
        return { "range": port.split("-") }
    elif "," in port:
        return { "set": port.split(",") }
    else:
        raise ValueError(f"Invalid port: {port}")
