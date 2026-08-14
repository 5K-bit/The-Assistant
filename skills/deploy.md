---
name: deploy
version: 0.1
description: Safely move a tested local revision into a target runtime and verify it.
commands: [deploy, release, ship]
reads: ["/wiki/projects", "/output/builds", "/output/debug"]
writes: ["/output/deploy", "/wiki/projects"]
---

# Deploy

## Role
Treat deployment as a controlled state transition.

## Procedure
1. Confirm target project and environment.
2. Check working tree and intended revision.
3. Confirm tests or explicitly record skipped verification.
4. Check configuration and secrets without exposing them.
5. Deploy only the intended revision.
6. Verify process/service health.
7. Verify the user-visible critical path.
8. Record rollback instructions.
9. Update canonical project state.

## Rules
- Never deploy an unintended dirty working tree.
- Never claim a remote service is healthy from a successful copy alone.
- Prefer reproducible release scripts over manual command sequences.
- Keep rollback possible.

## Output
`/output/deploy/YYYY-MM-DD-<project>-<revision>.md`
