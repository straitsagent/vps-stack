#!/usr/bin/env python3
"""Host system-metrics collector — writes /root/research/system/vps_health.json atomically.
Stdlib only. Runs as root via systemd every 30 min.
Per-metric error isolation: on any failure, that metric's value is {"error": "..."}
"""

import json, os, re, shutil, subprocess, tempfile, time
from datetime import datetime, timezone

OUTPUT_DIR = "/root/research/system"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "vps_health.json")


def _df():
    """Return list of {mount, pct_used, total_gb, used_gb, available_gb}."""
    try:
        r = subprocess.run(
            ["df", "-BG"],
            capture_output=True, text=True, timeout=10,
        )
        r.check_returncode()
        mounts = []
        for line in r.stdout.strip().split("\n")[1:]:
            parts = line.split()
            if len(parts) >= 6:
                mounts.append({
                    "mount": parts[5],
                    "total_gb": parts[1].rstrip("G") if parts[1].endswith("G") else parts[1],
                    "used_gb": parts[2].rstrip("G") if parts[2].endswith("G") else parts[2],
                    "available_gb": parts[3].rstrip("G") if parts[3].endswith("G") else parts[3],
                    "pct_used": parts[4].rstrip("%"),
                })
        return mounts
    except Exception as e:
        return {"error": str(e)}


def _memory():
    """Return {total_mib, used_mib, available_mib, pct_used, pct_available}."""
    try:
        meminfo = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    meminfo[key] = int(val)
        total = meminfo.get("MemTotal", 0) // 1024
        available = meminfo.get("MemAvailable", 0) // 1024
        used = total - available
        return {
            "total_mib": total,
            "used_mib": used,
            "available_mib": available,
            "pct_used": round(used / total * 100, 1) if total else 0,
            "pct_available": round(available / total * 100, 1) if total else 0,
        }
    except Exception as e:
        return {"error": str(e)}


def _load():
    """Return {load_1m, load_5m, load_15m, cores}."""
    try:
        avg = os.getloadavg()
        cores = os.cpu_count() or 1
        return {
            "load_1m": round(avg[0], 2),
            "load_5m": round(avg[1], 2),
            "load_15m": round(avg[2], 2),
            "cores": cores,
        }
    except Exception as e:
        return {"error": str(e)}


def _docker_ps():
    """Return {running, exited, restarting, total, containers: {name: state}}."""
    try:
        r = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=15,
        )
        r.check_returncode()
        containers = {}
        running = exited = restarting = 0
        for line in r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) < 2:
                continue
            name, status = parts[0], parts[1]
            containers[name] = status
            if status.startswith("Up"):
                running += 1
            elif status.startswith("Exited"):
                exited += 1
            elif status.startswith("Restarting"):
                restarting += 1
        return {
            "running": running,
            "exited": exited,
            "restarting": restarting,
            "total": len(containers),
            "containers": containers,
        }
    except Exception as e:
        return {"error": str(e)}


def _backup():
    """Return {service: {Result, ExecMainStatus, ExecMainExitTimestamp}, timer_active: bool}."""
    result = {}
    try:
        r = subprocess.run(
            ["systemctl", "show", "drive-backup.service", "--property=Result,ExecMainStatus,ExecMainExitTimestamp"],
            capture_output=True, text=True, timeout=10,
        )
        r.check_returncode()
        props = {}
        for line in r.stdout.strip().split("\n"):
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v
        result["service"] = props
    except Exception as e:
        result["service"] = {"error": str(e)}
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "drive-backup.timer"],
            capture_output=True, text=True, timeout=5,
        )
        result["timer_active"] = r.stdout.strip() == "active"
    except Exception as e:
        result["timer_active"] = False
    return result


def _uptime():
    """Return uptime_seconds and formatted string."""
    try:
        with open("/proc/uptime") as f:
            uptime_secs = float(f.read().split()[0])
        days = int(uptime_secs // 86400)
        hours = int((uptime_secs % 86400) // 3600)
        minutes = int((uptime_secs % 3600) // 60)
        return {
            "uptime_seconds": uptime_secs,
            "uptime_formatted": f"{days}d {hours}h {minutes}m",
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    data = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "disk": _df(),
        "memory": _memory(),
        "load": _load(),
        "docker": _docker_ps(),
        "backup": _backup(),
        "uptime": _uptime(),
    }
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    # Atomic write via tempfile + rename
    tmp = tempfile.NamedTemporaryFile(
        dir=OUTPUT_DIR, prefix="vps_health_tmp_", suffix=".json",
        delete=False, mode="w",
    )
    try:
        json.dump(data, tmp, indent=2)
        tmp.close()
        shutil.move(tmp.name, OUTPUT_FILE)
    except Exception:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
