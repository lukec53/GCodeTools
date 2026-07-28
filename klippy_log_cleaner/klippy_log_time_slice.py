#!/usr/bin/env python3
"""
Keep only log lines whose timestamps fall within a daily time range (e.g. 11:00–14:00).

Klippy lines look like:
  [INFO] 2026-03-25 12:34:56,789 [root] ...
Lines without a leading timestamp (config dumps, continuations) are kept only if the
last seen timestamp was inside the range.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, time
from pathlib import Path

# Matches Klippy-style timestamps anywhere in the line prefix
_TS_RE = re.compile(
    r"(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2}) "
    r"(?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2}),(?P<ms>\d{3})"
)


def _parse_hhmm(s: str) -> time:
    s = s.strip()
    parts = s.split(":")
    if len(parts) == 2:
        h, m = int(parts[0]), int(parts[1])
        return time(h, m, 0)
    if len(parts) == 3:
        h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
        return time(h, m, sec)
    raise ValueError(f"Expected HH:MM or HH:MM:SS, got {s!r}")


def _time_in_window(t: time, start: time, end: time) -> bool:
    """Inclusive on both ends; supports windows that cross midnight."""
    tt = t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1e6
    ts = start.hour * 3600 + start.minute * 60 + start.second + start.microsecond / 1e6
    te = end.hour * 3600 + end.minute * 60 + end.second + end.microsecond / 1e6
    if ts <= te:
        return ts <= tt <= te
    return tt >= ts or tt <= te


def _parse_line_ts(line: str) -> datetime | None:
    m = _TS_RE.search(line)
    if not m:
        return None
    return datetime(
        int(m["y"]),
        int(m["mo"]),
        int(m["d"]),
        int(m["h"]),
        int(m["mi"]),
        int(m["s"]),
        int(m["ms"]) * 1000,
    )


def slice_klippy_log(
    input_path: Path,
    output_path: Path,
    time_start: time,
    time_end: time,
    date_filter: str | None = None,
) -> tuple[int, int]:
    """
    Copy lines in [time_start, time_end] each day (optionally only for ``date_filter``).

    Returns (lines_read, lines_written).
    """
    date_obj = None
    if date_filter:
        date_obj = datetime.strptime(date_filter, "%Y-%m-%d").date()

    lines_read = 0
    lines_out: list[str] = []
    include_continuation = False

    with open(input_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            lines_read += 1
            dt = _parse_line_ts(line)
            if dt is not None:
                if date_obj is not None and dt.date() != date_obj:
                    include_continuation = False
                    continue
                include_continuation = _time_in_window(dt.time(), time_start, time_end)
                if include_continuation:
                    lines_out.append(line)
                continue

            if include_continuation:
                lines_out.append(line)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as out:
        out.writelines(lines_out)

    return lines_read, len(lines_out)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Keep Klippy log lines between two times of day (inclusive)."
    )
    p.add_argument("input", type=Path, help="Source klippy.log")
    p.add_argument("output", type=Path, help="Output path for the sliced log")
    p.add_argument(
        "--from",
        dest="time_from",
        required=True,
        metavar="TIME",
        help="Window start (HH:MM or HH:MM:SS), inclusive",
    )
    p.add_argument(
        "--to",
        dest="time_to",
        required=True,
        metavar="TIME",
        help="Window end (HH:MM or HH:MM:SS), inclusive",
    )
    p.add_argument(
        "--date",
        dest="date_filter",
        metavar="YYYY-MM-DD",
        help="If set, only include lines on this calendar day",
    )
    args = p.parse_args()

    t0 = _parse_hhmm(args.time_from)
    t1 = _parse_hhmm(args.time_to)

    n_in, n_out = slice_klippy_log(
        args.input,
        args.output,
        t0,
        t1,
        date_filter=args.date_filter,
    )
    print(f"Read {n_in:,} lines, wrote {n_out:,} lines → {args.output}")


if __name__ == "__main__":
    main()
