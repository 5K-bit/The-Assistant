---
name: hardware
version: 0.1
description: Evaluate, inventory, configure, and integrate physical devices into the user's ecosystem.
commands: [hardware, device, comparehardware, setupdevice]
reads: ["/wiki/infra", "/wiki/projects", "/output/research"]
writes: ["/wiki/infra", "/output/hardware"]
---

# Hardware

## Role
Treat hardware as a system component with a job, interface, power requirement, networking path, and maintenance cost.

## Procedure
1. Identify the intended role.
2. Check current hardware already owned.
3. Identify interfaces: USB, GPIO, BLE, Wi-Fi, LoRa, Ethernet, battery, display, etc.
4. Determine software/driver support.
5. Evaluate whether the device adds a real capability or duplicates one.
6. Record required accessories separately from included hardware.
7. Define how it joins OBEOS or remains independent.

## Rules
- Verify current specs before purchase recommendations.
- Explicitly distinguish included battery from battery-compatible.
- Prefer reusable/interchangeable components.
- Record power and thermal constraints.

## Output
`/output/hardware/YYYY-MM-DD-<device>.md`
