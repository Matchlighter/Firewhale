Firewhale
===

NFTables rule management for Docker Containers, Docker Compose, and Docker Swarm.

Note that this tool is not perfect and intended more as an extra layer of security rather than as the primary layer. This is due to it's reliance on Docker events - there is a short period of time between a container starting and Firewhale applying rules.

See `./examples/` directory for deployment examples.

## Architectures

There are two main modes of operation: `Local` and `Swarm`.

### Local
In local mode, only one container is needed. This container handles monitoring Docker events and applying any necessary NFTables rules.

### Swarm
Since Docker Swarm is a distributed system, Firewhale will need to be deployed as one as well. In this mode, 3 services need to be deployed (see also `./examples/docker-compose.swarm.yml`):

Firewhale consists of up to 3 services:
1. The container observer
   - It monitors the Docker socket events on each node and publishes any necessary changes to Redis.
   - It subscribes (via Redis) to changes announced by other nodes.
   - It instructs the `NFAgent` to make any necessary changes.
2. The NFTables Agent
   - It receives NFTable instructions and makes the necessary changes to the local node.
3. Redis
   - Handles cross-node communication and state tracking

## Configuration Examples

```yml
---
services:
  your-reverse-proxy:
    image: caddy/caddy:latest

  some-ingress-tunnel:
    images: ...
    labels:
      firewhale.enabled: true
      firewhale.outbound-rules: |
        - tcp; caddy.caddy; 80;
        - tcp; caddy.caddy; 443;
      firewhale.inbound-rules: |
        - tcp; 10.0.0.0/24; 80;
        - tcp; 10.0.0.0/24; 443;

```

### Rule Format
`PROTOCOL; HOST; DEST PORT(s); key:value; key:value`

Examples:
- `tcp; *; 80,443`
- `tcp; *; 80-87`
- `internet`
- `local-networks`
- `!10.0.1.0/24`
- `tcp; 10.0.0.0/24; 80,443`
- `tcp; 10.0.0.0-10.0.0.10; 80,443`
- `tcp; docker_network_name; 80,443`
- `tcp; container_name.docker_network_name; 80,443`
- `tcp; swarm_service.docker_network_name; 80,443`
- `tcp; caddy.caddy; 80,443`
- `tcp; caddy.caddy; 80,443; sport:8000-9000; jump:xyz-chain`
- `tcp; caddy.caddy; 80,443; comment:"Firewhale rule for Caddy"`

#### Keys
- `sport` - Source port
- `dport` - Destination port
- `comment:` - Optional comment to add to the NFT Rule.
- `jump:` - Advanced usage if you have externally-defined NFT chains that you want to invoke.
- `counter` - Advanced usage; see NFTables documentation for this term.
- `log_prefix` - Advanced usage; see NFTables documentation for this term.
