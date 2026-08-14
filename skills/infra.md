---
name: infra
version: 0.1
description: Track and operate the user's physical and cloud computing topology.
commands: [infra, nodes, network, servicestatus]
reads: ["/wiki/infra", "/wiki/projects", "/output"]
writes: ["/wiki/infra", "/output/infra"]
---

# Infrastructure

## Role
Maintain an accurate map of devices, nodes, services, and links.

## Known Architecture Pattern
The ecosystem may include devices such as Blackcomputer, Legion, Sentinel, Raspberry Pi nodes, and AWS/cloud services. The vault is authoritative for current inventory.

## Canonical Data
Store under:
`/wiki/infra/`

Track:
- Device name
- Role
- OS
- IP/Tailscale identity when intentionally stored
- Services
- Ports/bindings
- Repositories
- Storage
- Last seen
- Dependencies
- Recovery method

## Procedure
1. Never assume a device is online.
2. Query live state when possible.
3. Compare live state with vault state.
4. Update stale inventory only from evidence.
5. Flag orphaned or duplicate services.

## Output
`/output/infra/YYYY-MM-DD-HHmm-infra-status.md`
