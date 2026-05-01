"""Lightweight memory instrumentation for diagnosing memory growth.

Each call to log_snapshot() emits a single line to the standard logger
prefixed with "MEMLOG", so a session can be analyzed with:

    grep MEMLOG ~/.astro-framing/app.log

Captured per snapshot: current RSS (via `ps`, matches macOS Activity
Monitor), max RSS ever reached (via resource.getrusage), gc generation
counts, and any extra kwargs the caller tags on.

After every emit the file handler is flushed and fsync'd so the line
hits disk before any caller-side allocation can hang the OS.
"""

import gc
import logging
import os
import resource
import subprocess
import sys

logger = logging.getLogger(__name__)


MEMORY_CEILING_MB = 4096
"""Hard ceiling: any allocation site that calls check_ceiling() will
abort if current RSS exceeds this. Better to render a black canvas than
swap-thrash the OS into a hang."""


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


def _fsync_handlers() -> None:
    """Flush + fsync any FileHandlers on the root logger so the line
    survives a sudden OS hang (e.g. swap-thrash before a >100GB blow-up)."""
    try:
        for h in logging.getLogger().handlers:
            try:
                h.flush()
            except Exception:
                pass
            stream = getattr(h, 'stream', None)
            if stream is not None:
                try:
                    os.fsync(stream.fileno())
                except Exception:
                    pass
    except Exception:
        pass


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
    _fsync_handlers()


def check_ceiling(label: str) -> None:
    """Abort the calling allocation if RSS already breaches MEMORY_CEILING_MB.

    Emits a CEILING_BREACH line first (so we always know what was about
    to allocate), then raises MemoryError. RenderWorker.run() catches it
    and emits a black image; non-worker callers must catch it themselves.
    """
    rss = _current_rss_bytes()
    if rss >= MEMORY_CEILING_MB * 1024 * 1024:
        log_snapshot(
            f"CEILING_BREACH {label}",
            limit_mb=MEMORY_CEILING_MB,
            rss_mb=f"{rss / (1024 * 1024):.1f}",
        )
        raise MemoryError(
            f"Memory ceiling breached at '{label}': "
            f"{rss / (1024 * 1024):.1f}MB >= {MEMORY_CEILING_MB}MB"
        )
