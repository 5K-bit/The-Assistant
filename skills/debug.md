---
name: debug
version: 0.1
description: Diagnose failures methodically and isolate root cause before changing the system.
commands: [debug, fix, diagnose]
reads: ["/wiki/projects", "/raw", "/output"]
writes: ["/output", "/wiki/projects"]
---

# Debug

## Role
Perform forensic debugging.

## Procedure
1. Capture the exact failure.
2. Establish expected behavior.
3. Identify the last known good state.
4. Separate environment, configuration, dependency, data, network, permission, and code failures.
5. Change one variable at a time when practical.
6. Prefer evidence from logs, exit codes, stack traces, service state, diffs, and reproducible commands.
7. Verify the fix.
8. Record root cause and prevention.

## Environment Awareness
The user's systems may span:
- Windows / PowerShell
- Linux / SteamOS
- AWS EC2
- Docker
- Tailscale
- Raspberry Pi
- local Python
- Git/GitHub

Never give commands for the wrong environment.

## Output
`/output/debug/YYYY-MM-DD-<project>-<issue>.md`

Include:
## Symptom
## Evidence
## Root Cause
## Fix
## Verification
## Prevention
