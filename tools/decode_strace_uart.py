#!/usr/bin/env python3
"""Summarize the fixed-frame HALOT UART from a strace text log.

Use with logs produced by record-uart.sh, for example:
    python3 tools/decode_strace_uart.py capture.strace --fd 28

The decoder handles strace's ``<unfinished ...>`` / ``<... resumed>`` pairs,
which matter when the one-byte UART reads block while other threads run.
It reports syscall-observed bytes and does not repair malformed responses.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path


START_RE = re.compile(
    r"^(?P<tid>\d+)\s+(?P<ts>\d+\.\d+)\s+"
    r"(?P<op>read|write)\((?P<fd>\d+)(?:<[^>]*>)?,"
)
RESUMED_RE = re.compile(
    r"^(?P<tid>\d+)\s+(?P<ts>\d+\.\d+)\s+"
    r"<\.\.\. (?P<op>read|write) resumed>"
)
RETURN_RE = re.compile(r"=\s+(?P<count>\d+)\s+<")
HEX_RE = re.compile(r"^[0-9a-fA-F]{2}$")


@dataclass
class Pending:
    tid: str
    op: str
    fd: int
    start_ts: float


@dataclass
class Event:
    seq: int
    tid: str
    op: str
    fd: int
    ts: float
    count: int
    data: bytearray = field(default_factory=bytearray)


def dump_bytes(line: str) -> bytes:
    """Parse one strace ``| OFFSET HEX... ASCII`` buffer line."""
    if not line.startswith(" | "):
        return b""
    fields = line[3:].split()
    if not fields:
        return b""
    result = bytearray()
    for token in fields[1:]:  # first token is the five-digit offset
        if not HEX_RE.fullmatch(token):
            break
        result.append(int(token, 16))
    return bytes(result)


def parse_events(path: Path, wanted_fd: int) -> tuple[list[Event], int]:
    pending: dict[str, Pending] = {}
    events: list[Event] = []
    active: Event | None = None
    line_number = 0

    def finish() -> None:
        nonlocal active
        if active is not None:
            active.data = active.data[: active.count]
            events.append(active)
            active = None

    with path.open("r", errors="replace") as source:
        for line_number, line in enumerate(source, 1):
            if line.startswith(" | "):
                if active is not None:
                    active.data.extend(dump_bytes(line))
                continue

            finish()

            match = START_RE.match(line)
            if match:
                tid, op, fd = match["tid"], match["op"], int(match["fd"])
                if "<unfinished ...>" in line:
                    pending[tid] = Pending(tid, op, fd, float(match["ts"]))
                    continue
                ret = RETURN_RE.search(line)
                if fd == wanted_fd and ret:
                    active = Event(
                        len(events), tid, op, fd, float(match["ts"]), int(ret["count"])
                    )
                continue

            match = RESUMED_RE.match(line)
            if match:
                tid, op = match["tid"], match["op"]
                info = pending.pop(tid, None)
                ret = RETURN_RE.search(line)
                if info and info.op == op and info.fd == wanted_fd and ret:
                    active = Event(
                        len(events), tid, op, info.fd, float(match["ts"]), int(ret["count"])
                    )

    finish()
    return events, line_number


def utc(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def command_from_frame(data: bytes) -> tuple[str, bool]:
    valid = (
        len(data) == 101
        and data[96:100] == b"\x55" * 4
        and data[100:101] == b"\n"
    )
    body = data[:96].rstrip(b" ") if len(data) >= 96 else data
    return body.decode("ascii", "replace"), valid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--fd", type=int, default=28, help="UART descriptor number (default: 28)")
    parser.add_argument("--events", action="store_true", help="print non-poll commands and replies")
    parser.add_argument("--cycles", action="store_true", help="summarize M678-to-M678 layer cycles")
    parser.add_argument("--limit", type=int, default=80, help="maximum detailed events to print")
    args = parser.parse_args()

    events, scanned_lines = parse_events(args.trace, args.fd)
    writes = [e for e in events if e.op == "write" and e.count > 0]
    reads = [e for e in events if e.op == "read" and e.count > 0]
    commands: list[tuple[Event, str, bool]] = []
    for event in writes:
        data = bytes(event.data[: event.count])
        text, valid = command_from_frame(data)
        commands.append((event, text, valid))

    rx = bytearray()
    replies: list[tuple[float, str]] = []
    for event in reads:
        data = bytes(event.data[: event.count])
        for value in data:
            rx.append(value)
            if value == 0x0A:
                raw = bytes(rx)
                replies.append((event.ts, raw.decode("ascii", "replace").rstrip("\r\n")))
                rx.clear()

    command_counts = collections.Counter(text.split(" ", 1)[0] for _, text, _ in commands)
    reply_counts = collections.Counter(text for _, text in replies)
    reply_kinds = collections.Counter(
        text.split("_", 1)[0] for _, text in replies if text
    )
    bad_frames = sum(not valid for _, _, valid in commands)
    captured_bytes = sum(len(e.data[: e.count]) for e in writes + reads)

    print(f"trace: {args.trace}")
    print(f"lines_scanned: {scanned_lines}")
    print(f"UART events: {len(events)} (read={len(reads)}, write={len(writes)})")
    print(f"UART payload bytes decoded: {captured_bytes}")
    print(f"complete RX lines: {len(replies)}; trailing partial RX bytes: {bytes(rx)!r}")
    print(f"writes not matching the 101-byte frame: {bad_frames}")
    print("TX command counts:")
    for name, count in command_counts.most_common():
        print(f"  {name}: {count}")
    print("RX reply-family counts:")
    for name, count in reply_kinds.most_common():
        print(f"  {name}: {count}")
    print("Most common complete RX strings:")
    for text, count in reply_counts.most_common(20):
        print(f"  {count:5} {text!r}")

    if args.events:
        selected: list[tuple[float, str]] = []
        for event, text, valid in commands:
            if text.split(" ", 1)[0] != "M114":
                selected.append((event.ts, f"TX {'OK' if valid else 'BAD'} {text}"))
        for ts, text in replies:
            if not text.startswith("M114_Busy"):
                selected.append((ts, f"RX {text}"))
        selected.sort(key=lambda item: item[0])
        print(f"Detailed events (first {args.limit}):")
        for ts, text in selected[: max(args.limit, 0)]:
            print(f"  {utc(ts)} {text}")

    if args.cycles:
        layer_commands = [
            (event, text) for event, text, _ in commands
            if text.startswith("M678 ")
        ]
        print("M678 cycles (state transitions are syscall-observed):")
        cycle_records: list[dict[str, object]] = []
        for index, (event, text) in enumerate(layer_commands):
            start = event.ts
            end = layer_commands[index + 1][0].ts if index + 1 < len(layer_commands) else float("inf")
            cycle_replies = [(ts, reply) for ts, reply in replies if start <= ts < end]
            ack = next((ts for ts, reply in cycle_replies if reply == "M678_Busy"), None)
            sentinel = next((ts for ts, reply in cycle_replies if reply == "M114_DELATLIGHT_OVER"), None)
            done = next((
                ts for ts, reply in cycle_replies
                if reply == "M114_OK" and (sentinel is None or ts > sentinel)
            ), None)
            states: list[str] = []
            for _, reply in cycle_replies:
                if not reply.startswith("M114_Busy"):
                    continue
                match = re.fullmatch(r"M114_Busy(?:_(\d+))?", reply)
                state = match.group(1) if match and match.group(1) else "plain"
                if not states or states[-1] != state:
                    states.append(state)

            def elapsed(when: float | None) -> str:
                return "-" if when is None else f"{when - start:.3f}s"

            period = "-" if end == float("inf") else f"{end - start:.3f}s"
            fields = dict(re.findall(r"(?:^| )(Z|U|D|T|P|M)([^ ]+)", text))
            cycle_records.append(
                {
                    "fields": fields,
                    "ack": None if ack is None else ack - start,
                    "sentinel": None if sentinel is None else sentinel - start,
                    "done": None if done is None else done - start,
                    "exposure": None if sentinel is None or done is None else done - sentinel,
                    "period": None if end == float("inf") else end - start,
                    "states": "/".join(states),
                }
            )
            safe_text = re.sub(r"(?:^| )L[^ ]+", " L<omitted>", text)
            print(
                f"  #{index + 1:04d} {utc(start)} ack={elapsed(ack)} "
                f"states={'/'.join(states) or '-'} sentinel={elapsed(sentinel)} "
                f"M114_OK={elapsed(done)} next={period} | {safe_text}"
            )

        def compact(values: list[float]) -> str:
            if not values:
                return "n=0"
            return (
                f"n={len(values)} median={statistics.median(values):.3f}s "
                f"range={min(values):.3f}..{max(values):.3f}s"
            )

        complete = [record for record in cycle_records if record["done"] is not None]
        print(
            "M678 lifecycle totals: "
            f"commands={len(cycle_records)} ack={sum(r['ack'] is not None for r in cycle_records)} "
            f"sentinel={sum(r['sentinel'] is not None for r in cycle_records)} "
            f"M114_OK_after_sentinel={len(complete)}"
        )
        print(
            "  ack latency: "
            + compact([r["ack"] for r in cycle_records if r["ack"] is not None])
        )
        print(
            "  M678 to DELATLIGHT_OVER: "
            + compact([r["sentinel"] for r in cycle_records if r["sentinel"] is not None])
        )
        print(
            "  DELATLIGHT_OVER to M114_OK: "
            + compact([r["exposure"] for r in complete if r["exposure"] is not None])
        )
        print(
            "  M678-to-next-M678 interval: "
            + compact([r["period"] for r in cycle_records if r["period"] is not None])
        )

        grouped: dict[tuple[str, ...], list[dict[str, object]]] = collections.defaultdict(list)
        for record in cycle_records:
            fields = record["fields"]
            key = tuple(str(fields.get(name, "?")) for name in ("Z", "U", "D", "T", "P", "M"))
            grouped[key].append(record)
        print("M678 timings grouped by command parameters (L omitted):")
        for key, records in grouped.items():
            if len(records) < 5:
                continue
            intervals = [r["period"] for r in records if r["period"] is not None]
            sentinels = [r["sentinel"] for r in records if r["sentinel"] is not None]
            exposure = [r["exposure"] for r in records if r["exposure"] is not None]
            label = " ".join(f"{name}{value}" for name, value in zip(("Z", "U", "D", "T", "P", "M"), key))
            print(
                f"  {label}: cycles={len(records)}; "
                f"to-sentinel[{compact(sentinels)}]; "
                f"sentinel-to-OK[{compact(exposure)}]; "
                f"cycle[{compact(intervals)}]"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
