"""System vitals.

Uses psutil when it is installed, otherwise per-platform stdlib probes.
A value that cannot be measured on this host is reported as null so the
HUD can show it as unknown; it is never estimated or filled in.
"""

import os
import shutil
import subprocess
import sys
import time

try:
    import psutil
except ImportError:
    psutil = None

_prev_cpu_sample = None


def _pct(part, whole):
    return round(part / whole * 100, 1) if whole else None


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


# Below this many jiffies of delta the sample is dominated by measurement
# noise rather than real load, so a fresh interval is taken instead.
_MIN_CPU_DELTA = 20


def _cpu_procfs():
    """CPU busy percentage from the delta between two /proc/stat samples."""
    global _prev_cpu_sample

    def sample():
        line = (_read("/proc/stat") or "").split("\n", 1)[0]
        if not line.startswith("cpu "):
            return None
        fields = [int(value) for value in line.split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        return sum(fields), idle

    current = sample()
    if current is None:
        return None

    previous = _prev_cpu_sample
    if previous is None or current[0] - previous[0] < _MIN_CPU_DELTA:
        # Either the first call, or polled again too soon for the counters
        # to have moved meaningfully: measure a fresh short interval.
        previous = current
        time.sleep(0.1)
        current = sample()
        if current is None:
            return None

    _prev_cpu_sample = current
    total_delta = current[0] - previous[0]
    idle_delta = current[1] - previous[1]
    if total_delta <= 0:
        return None
    return _pct(max(0, total_delta - idle_delta), total_delta)


def _mem_procfs():
    text = _read("/proc/meminfo")
    if not text:
        return None
    values = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            values[key] = int(parts[0])
    total, available = values.get("MemTotal"), values.get("MemAvailable")
    if not total or available is None:
        return None
    return _pct(total - available, total)


def _mem_darwin():
    """Used memory percentage on macOS via sysctl + vm_stat."""
    try:
        total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
        out = subprocess.check_output(["vm_stat"], text=True)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    page_size, pages = 4096, {}
    for line in out.splitlines():
        if "page size of" in line:
            page_size = int(line.split("page size of")[1].split()[0])
        key, _, rest = line.partition(":")
        rest = rest.strip().rstrip(".")
        if rest.isdigit():
            pages[key.strip()] = int(rest)
    used = sum(
        pages.get(key, 0)
        for key in ("Pages active", "Pages wired down", "Pages occupied by compressor")
    )
    return _pct(used * page_size, total)


def _uptime_seconds():
    text = _read("/proc/uptime")
    if text:
        try:
            return int(float(text.split()[0]))
        except (ValueError, IndexError):
            pass
    if psutil is not None:
        return int(time.time() - psutil.boot_time())
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(["sysctl", "-n", "kern.boottime"], text=True)
            boot = int(out.split("sec =")[1].split(",")[0].strip())
            return int(time.time() - boot)
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return None
    return None


def _format_uptime(seconds):
    if seconds is None:
        return None
    hours, remainder = divmod(seconds, 3600)
    return f"{hours:02d}:{remainder // 60:02d}"


def read(disk_path="/"):
    """Return the current vitals snapshot."""
    if psutil is not None:
        cpu = psutil.cpu_percent(interval=None) or psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent
        source = "psutil"
    elif sys.platform.startswith("linux"):
        cpu, mem, source = _cpu_procfs(), _mem_procfs(), "procfs"
    elif sys.platform == "darwin":
        cpu, mem, source = None, _mem_darwin(), "sysctl"
    else:
        cpu, mem, source = None, None, "unavailable"

    try:
        usage = shutil.disk_usage(disk_path)
        disk = _pct(usage.used, usage.total)
        disk_total = usage.total
    except OSError:
        disk, disk_total = None, None

    try:
        load = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        load = None

    uptime = _uptime_seconds()
    return {
        "cpu": cpu,
        "ram": mem,
        "disk": disk,
        "disk_total": disk_total,
        "uptime_seconds": uptime,
        "uptime": _format_uptime(uptime),
        "load": load,
        "cores": os.cpu_count(),
        "source": source,
    }
