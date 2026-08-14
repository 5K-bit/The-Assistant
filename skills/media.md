---
name: media
version: 0.1
description: Operate and plan self-hosted media, game streaming, music, and entertainment services.
commands: [media, jellyfin, musicserver, stream]
reads: ["/wiki/infra", "/wiki/projects"]
writes: ["/output/media", "/wiki/projects"]
---

# Media

## Role
Handle the user's self-hosted and device-based media ecosystem.

## Scope
- Jellyfin
- Music server experiments
- Sync/watch-together workflows
- Storage planning
- Remote access through private networking
- Legion gaming/streaming configuration
- Client compatibility

## Procedure
1. Identify server, client, network path, and media source.
2. Verify whether the problem is server-side, client-side, codec, storage, permissions, or network.
3. Prefer private remote access.
4. Preserve library data and metadata during migrations.
5. Record working server addresses and topology only when intentionally stored.

## Output
`/output/media/YYYY-MM-DD-<topic>.md`
