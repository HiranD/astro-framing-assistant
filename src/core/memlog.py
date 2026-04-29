"""Lightweight memory instrumentation for diagnosing memory growth.

Each call to log_snapshot() emits a single line to the standard logger
prefixed with "MEMLOG", so a session can be analyzed with:

    grep MEMLOG ~/.astro-framing/app.log

Captured per snapshot: current RSS (via `ps`, matches macOS Activity
Monitor), max RSS ever reached (via resource.getrusage), gc generation
counts, and any extra kwargs the caller tags on.
"""

import gc
import logging
import os
import resource
import subprocess
import sys

logger = logging.getLogger(__name__)


def _max_rss_bytes() -> int:
    try:
        ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes; Linux reports kilobytes
        return ru if sys.platform == 'darwin' else ru * 1024
    except Exception:
        return 0


def _current_rss_bytes() -> int:
    try:
        out = subprocess.check_output(
            ['ps', '-o', 'rss=', '-p', str(os.getpid())],
            stderr=subprocess.DEVNULL,
            timeout=1.0,
        )
        return int(out.strip()) * 1024
    except Exception:
        return 0


def log_snapshot(label: str, **extra) -> None:
    rss = _current_rss_bytes()
    max_rss = _max_rss_bytes()
    counts = gc.get_count()
    parts = [
        f"MEMLOG {label}",
        f"rss={rss / (1024 * 1024):.1f}MB",
        f"max={max_rss / (1024 * 1024):.1f}MB",
        f"gc=({counts[0]},{counts[1]},{counts[2]})",
    ]
    for k, v in extra.items():
        parts.append(f"{k}={v}")
    logger.info(" ".join(parts))
