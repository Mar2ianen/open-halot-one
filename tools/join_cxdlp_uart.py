#!/usr/bin/env python3
"""Join one CXDLP v2 layer table to M678 frames in a PrinterUI strace capture.

This is an offline analyzer. It reads local CXDLP, strace, and decoder-summary
files only; it never opens a printer device. It writes a per-layer TSV and can
write an Odyssey runtime schedule after all join checks pass.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import decimal
import hashlib
import json
import re
import sys
from pathlib import Path

START_RE = re.compile(r"^(?P<tid>\d+)\s+(?P<ts>\d+\.\d+)\s+(?P<op>read|write)\((?P<fd>\d+)(?:<[^>]*>)?,")
RESUMED_RE = re.compile(r"^(?P<tid>\d+)\s+(?P<ts>\d+\.\d+)\s+<\.\.\. (?P<op>read|write) resumed>")
RETURN_RE = re.compile(r"=\s+(?P<count>\d+)\s+<")
HEX_RE = re.compile(r"^[0-9a-fA-F]{2}$")
FIELD_RE = re.compile(r"(?:^| )(Z|U|D|T|P|M|L)([^ ]+)")
CYCLE_RE = re.compile(r"^\s+#(?P<n>\d+) (?P<time>\S+) ack=(?P<ack>\S+) states=(?P<states>\S+) sentinel=(?P<sentinel>\S+) M114_OK=(?P<done>\S+) next=(?P<next>\S+) \|")


def u16(data: bytes, pos: int) -> tuple[int, int]:
    return int.from_bytes(data[pos:pos + 2], "big"), pos + 2


def u32(data: bytes, pos: int) -> tuple[int, int]:
    return int.from_bytes(data[pos:pos + 4], "big"), pos + 4


def take(data: bytes, pos: int, n: int) -> tuple[bytes, int]:
    end = pos + n
    if end > len(data):
        raise ValueError("truncated CXDLP structure")
    return data[pos:end], end


def skip_sized(data: bytes, pos: int) -> tuple[bytes, int]:
    n, pos = u32(data, pos)
    return take(data, pos, n)


def read_cxdlp_v2(path: Path) -> tuple[dict[str, object], list[dict[str, int]]]:
    data = path.read_bytes()
    pos = 0
    magic_len, pos = u32(data, pos)
    magic, pos = take(data, pos, magic_len)
    if magic_len != 9 or not magic.startswith(b"CXSW3D"):
        raise ValueError("not a CXSW3D CXDLP container")
    version, pos = u16(data, pos)
    if version != 2:
        raise ValueError(f"expected CXDLP v2, got v{version}")
    model, pos = skip_sized(data, pos)
    model = model.rstrip(b"\x00").decode("utf-8")
    layer_count, pos = u16(data, pos)
    width, pos = u16(data, pos)
    height, pos = u16(data, pos)
    _, pos = take(data, pos, 64)
    for pixels in (116 * 116, 290 * 290, 290 * 290):
        _, pos = take(data, pos, pixels * 2)
        separator, pos = take(data, pos, 2)
        if separator != b"\r\n":
            raise ValueError("bad preview separator")
    texts = []
    for _ in range(3):
        raw, pos = skip_sized(data, pos)
        texts.append(raw.decode("utf-16-be"))
    params = []
    for _ in range(11):
        value, pos = u16(data, pos)
        params.append(value)
    areas = []
    for _ in range(layer_count):
        value, pos = u32(data, pos)
        areas.append(value)
    separator, pos = take(data, pos, 2)
    if separator != b"\r\n":
        raise ValueError("bad area table separator")
    layers = []
    for index in range(layer_count):
        record_area, pos = u32(data, pos)
        records, pos = u32(data, pos)
        _, pos = take(data, pos, records * 6)
        separator, pos = take(data, pos, 2)
        if separator != b"\r\n":
            raise ValueError(f"bad layer separator at {index}")
        layers.append({"index0": index, "area_table_raw": areas[index],
                       "area_record_raw": record_area, "run_records": records})
    if pos != len(data) - 17:
        raise ValueError(f"unexpected trailing data: layer_end={pos}, expected={len(data)-17}")
    footer_magic_len, pos = u32(data, pos)
    footer_magic, pos = take(data, pos, footer_magic_len)
    if footer_magic_len != 9 or not footer_magic.startswith(b"CXSW3D"):
        raise ValueError("bad CXDLP footer marker")
    stored_checksum, pos = u32(data, pos)
    calculated_checksum = 0
    for byte in data[:-4]:
        calculated_checksum ^= byte
    if pos != len(data) or (stored_checksum & 0xFF) != calculated_checksum:
        raise ValueError("CXDLP v2 XOR checksum mismatch")
    return ({"version": version, "model": model, "layers": layer_count,
             "width": width, "height": height, "layer_height": texts[2],
             "normal_exposure_raw": params[0], "wait_before_cure_raw": params[1],
             "bottom_exposure_raw": params[2], "bottom_layers": params[3],
             "bottom_lift_height_raw": params[4], "bottom_lift_speed_raw": params[5],
             "lift_height_raw": params[6], "lift_speed_raw": params[7],
             "retract_speed_raw": params[8], "bottom_pwm_raw": params[9],
             "pwm_raw": params[10], "area_table_mismatches": sum(
                 row["area_table_raw"] != row["area_record_raw"] for row in layers)}, layers)


def dump_bytes(line: str) -> bytes:
    if not line.startswith(" | "):
        return b""
    parts = line[3:].split()
    out = bytearray()
    for token in parts[1:]:  # the first token is strace's byte offset
        if not HEX_RE.fullmatch(token):
            break
        out.append(int(token, 16))
    return bytes(out)


def decode_m678(path: Path, wanted_fd: int = 28) -> tuple[list[dict[str, object]], dict[str, int]]:
    pending: dict[str, tuple[str, int]] = {}
    active: dict[str, object] | None = None
    commands: list[dict[str, object]] = []
    scanned = 0
    bad_frames = 0

    def finish() -> None:
        nonlocal active, bad_frames
        if active is None:
            return
        data = bytes(active["data"][:active["count"]])
        if len(data) != 101 or data[96:100] != b"\x55" * 4 or data[100:101] != b"\n":
            bad_frames += 1
        body = data[:96].rstrip(b" ").decode("ascii", "replace")
        if body.startswith("M678 "):
            fields = dict(FIELD_RE.findall(body))
            commands.append({"time_epoch": float(active["ts"]), "text": body,
                             "fields": fields, "valid_frame": len(data) == 101
                             and data[96:100] == b"\x55" * 4 and data[100:101] == b"\n"})
        active = None

    with path.open("r", errors="replace") as source:
        for scanned, line in enumerate(source, 1):
            if line.startswith(" | "):
                if active is not None:
                    active["data"].extend(dump_bytes(line))
                continue
            finish()
            match = START_RE.match(line)
            if match:
                tid, op, fd = match["tid"], match["op"], int(match["fd"])
                if op != "write" or fd != wanted_fd:
                    continue
                if "<unfinished ...>" in line:
                    pending[tid] = (op, fd)
                    continue
                ret = RETURN_RE.search(line)
                if ret:
                    active = {"ts": match["ts"], "count": int(ret["count"]), "data": bytearray()}
                continue
            match = RESUMED_RE.match(line)
            if match:
                info = pending.pop(match["tid"], None)
                ret = RETURN_RE.search(line)
                if info == ("write", wanted_fd) and ret:
                    active = {"ts": match["ts"], "count": int(ret["count"]), "data": bytearray()}
    finish()
    return commands, {"lines_scanned": scanned, "bad_uart_frames": bad_frames}


def read_cycle_summaries(path: Path) -> dict[int, dict[str, str]]:
    result = {}
    with path.open("r", errors="replace") as source:
        for line in source:
            match = CYCLE_RE.match(line)
            if match:
                row = match.groupdict()
                result[int(row["n"])] = row
    return result


def runtime_schedule(
    commands: list[dict[str, object]], job_sha256: str
) -> dict[str, object]:
    """Convert a joined print into Odyssey's job-bound offline schedule."""
    ranges: list[dict[str, object]] = []
    names = ("Z", "U", "D", "P", "M")
    layer_height: str | None = None
    for index, command in enumerate(commands):
        fields = command["fields"]
        missing = [name for name in (*names, "T", "L") if name not in fields]
        if missing:
            raise ValueError(f"M678 frame {index + 1} lacks fields: {', '.join(missing)}")
        if not command["valid_frame"]:
            raise ValueError(f"M678 frame {index + 1} is not a valid 101-byte UART frame")
        if layer_height is None:
            layer_height = fields["T"]
        elif fields["T"] != layer_height:
            raise ValueError(f"M678 frame {index + 1} changes T from {layer_height} to {fields['T']}")
        key = tuple(fields[name] for name in names)
        if ranges and ranges[-1]["_key"] == key:
            ranges[-1]["end_layer_exclusive"] = index + 1
            continue
        tokens: dict[str, str] = {name.lower(): fields[name] for name in names}
        if index == 0:
            # Preserve the observed first-layer L value; its physical unit is
            # still unverified, despite the host's full-panel-area formula.
            tokens["initial_full_panel_area_mm2"] = fields["L"]
        ranges.append({
            "first_layer": index,
            "end_layer_exclusive": index + 1,
            "tokens": tokens,
            "_key": key,
        })
    for item in ranges:
        item.pop("_key")
    if layer_height is None:
        raise ValueError("cannot export a runtime schedule without M678 frames")
    return {
        "layer_count": len(commands),
        "layer_height": layer_height,
        "job_sha256": job_sha256,
        "ranges": ranges,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cxdlp", type=Path)
    parser.add_argument("strace", type=Path)
    parser.add_argument("cycle_report", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--schedule-json", type=Path,
                        help="optional new output path for a fully validated Odyssey runtime schedule")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing TSV: {args.output}")
    if args.schedule_json is not None and args.schedule_json.exists():
        raise SystemExit(f"refusing to overwrite existing schedule: {args.schedule_json}")
    meta, layers = read_cxdlp_v2(args.cxdlp)
    commands, trace_info = decode_m678(args.strace)
    cycles = read_cycle_summaries(args.cycle_report)
    if len(commands) != meta["layers"]:
        raise SystemExit(f"layer/M678 count mismatch: {meta['layers']} file layers vs {len(commands)} M678")
    if len(cycles) != len(commands):
        raise SystemExit(f"cycle report has {len(cycles)} entries for {len(commands)} M678 frames")
    incomplete_cycles = [
        index for index in range(1, len(commands) + 1)
        if index not in cycles or any(cycles[index][key] == "-" for key in ("ack", "sentinel", "done"))
    ]

    keys = ("Z", "U", "D", "T", "P", "M")
    mismatches = []
    field_groups = collections.Counter()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as out:
        columns = ["layer_1based", "layer_0based", "tx_time_utc", "Z", "U", "D", "T", "P", "M",
                   "L_tx", "L_expected_from_file", "L_matches", "area_table_raw",
                   "area_record_raw", "vertical_run_records", "ack_s", "busy_states",
                   "delatlight_over_s", "m114_ok_s", "next_m678_s"]
        out.write("\t".join(columns) + "\n")
        for n, (command, layer) in enumerate(zip(commands, layers), 1):
            fields = command["fields"]
            # The per-layer record is authoritative. The redundant header
            # area table is reported separately and may disagree in other
            # files without changing the record value consumed by the host.
            expected = (
                decimal.Decimal("10368")
                if n == 1
                else decimal.Decimal(layer["area_record_raw"]) / decimal.Decimal(1000)
            )
            try:
                l_tx = decimal.Decimal(fields["L"])
                matches = abs(l_tx - expected) <= decimal.Decimal("0.000001")
            except (KeyError, decimal.InvalidOperation):
                l_tx, matches = decimal.Decimal("NaN"), False
            if not matches:
                mismatches.append((n, fields.get("L"), str(expected)))
            field_groups[tuple(fields.get(k, "?") for k in keys)] += 1
            ts = dt.datetime.fromtimestamp(float(command["time_epoch"]), dt.timezone.utc).strftime("%H:%M:%S.%f")[:-3]
            cycle = cycles[n]
            values = [str(n), str(n - 1), ts,
                      *(fields.get(k, "") for k in keys), fields.get("L", ""), str(expected),
                      "yes" if matches else "NO", str(layer["area_table_raw"]),
                      str(layer["area_record_raw"]), str(layer["run_records"]),
                      cycle["ack"].removesuffix("s"), cycle["states"],
                      cycle["sentinel"].removesuffix("s"), cycle["done"].removesuffix("s"),
                      cycle["next"].removesuffix("s")]
            out.write("\t".join(values) + "\n")

    print("CXDLP metadata:", meta)
    print("UART parser:", trace_info)
    print("M678 frames:", len(commands), "frame_bad_count:", sum(not c["valid_frame"] for c in commands))
    print("M678 parameter groups (Z,U,D,T,P,M):")
    for group, count in field_groups.items():
        print(" ", group, "cycles=", count)
    print("area-table/record mismatches:", meta["area_table_mismatches"])
    print("L-vs-CXDLP expected mismatches:", len(mismatches))
    if mismatches:
        print("first mismatches:", mismatches[:12])
    print("output:", args.output)
    if args.schedule_json is not None:
        if meta["model"] != "CL-60" or meta["width"] != 1620 or meta["height"] != 2560:
            raise SystemExit("refusing CL-60 schedule export: CXDLP is not a 1620x2560 CL-60 job")
        invalid_frames = sum(not command["valid_frame"] for command in commands)
        if invalid_frames:
            raise SystemExit(f"refusing schedule export: {invalid_frames} M678 frames are malformed")
        if meta["area_table_mismatches"] or mismatches:
            raise SystemExit("refusing schedule export: CXDLP or transmitted L values do not validate")
        if incomplete_cycles:
            raise SystemExit(f"refusing schedule export: {len(incomplete_cycles)} M678 cycles are incomplete")
        job_sha256 = hashlib.sha256(args.cxdlp.read_bytes()).hexdigest()
        schedule = runtime_schedule(commands, job_sha256)
        args.schedule_json.parent.mkdir(parents=True, exist_ok=True)
        with args.schedule_json.open("x") as schedule_file:
            json.dump(schedule, schedule_file, indent=2)
            schedule_file.write("\n")
        print("runtime_schedule_ranges:", len(schedule["ranges"]))
        print("runtime_schedule:", args.schedule_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
