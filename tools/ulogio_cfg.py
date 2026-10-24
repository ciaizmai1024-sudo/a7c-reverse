#!/usr/bin/env python3
# 来源：100.122.234.78（2015 MacBook）上 `qoderclicn -m DeepSeek-Flash` 子代理产出，2026-10-24；主会话已复核。
# 复核点：LOGB=0x03085000/0x478000、PRTB=0x034FD000/0x8000（首尾相接，都在出厂 memrsv=0x75e000@0x02E68000 保留窗内）、
# TELN 标签串 0x98 / 值 dword 0x94 = 0、TERM=1；在机身 2.00 那份上跑通（128 顶层 / 130 含嵌套，往返无损）。
"""Reader/editor for ulogio /setting TLV files.

Record layout (little-endian):
    u32 total_len   (includes these 4 bytes, the 4-byte tag and the payload)
    char tag[4]
    u8   payload[total_len - 8]

The payload is zero-padded to a 4-byte boundary.  A file is a sequence of
top-level records with no file header, count, checksum or trailer.
FBOX is a container whose payload is itself a sequence of records.
"""

import argparse
import hashlib
import json
import shutil
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

CONTAINER_TAGS = {b"FBOX"}
STRING_TAGS = {b"LGNM", b"FLTF", b"RCVF", b"ALGP", b"ALGB", b"ALGD", b"ALGK", b"ALGT"}
BOOL_TAGS = {b"RECO", b"DBGL", b"FLTA", b"TERM", b"TELN", b"CHAN", b"ISYS", b"SFLT", b"CFLT"}


class FormatError(Exception):
    pass


@dataclass
class Record:
    tag: bytes
    data: bytearray
    offset: int
    children: list = None
    container_error: str = None


def align4(n):
    return (n + 3) & ~3


def read_u32(buf, off):
    if off + 4 > len(buf):
        raise FormatError("read past end at 0x%x" % off)
    return struct.unpack_from("<I", buf, off)[0]


def parse_records(buf, base=0, depth=0):
    if depth > 16:
        raise FormatError("nesting too deep at 0x%x" % base)
    records = []
    off = 0
    while off < len(buf):
        if off + 8 > len(buf):
            raise FormatError(
                "truncated header at 0x%x (%d byte(s) left)" % (base + off, len(buf) - off)
            )
        total_len = read_u32(buf, off)
        if total_len < 8:
            raise FormatError("invalid length %d at 0x%x" % (total_len, base + off))
        if total_len % 4:
            raise FormatError(
                "length %d at 0x%x is not 4-byte aligned" % (total_len, base + off)
            )
        if off + total_len > len(buf):
            raise FormatError(
                "record at 0x%x overruns its container (%d > %d)"
                % (base + off, off + total_len, len(buf))
            )
        tag = bytes(buf[off + 4 : off + 8])
        if not all(32 <= c < 127 for c in tag):
            raise FormatError("non-printable tag %r at 0x%x" % (tag, base + off + 4))
        data = bytearray(buf[off + 8 : off + total_len])
        rec = Record(tag=tag, data=data, offset=base + off)
        if tag in CONTAINER_TAGS:
            try:
                rec.children = parse_records(data, base=base + off + 8, depth=depth + 1)
            except FormatError as exc:
                rec.children = None
                rec.container_error = str(exc)
        records.append(rec)
        off += total_len
    return records


def encode_record(rec):
    if rec.children is not None:
        payload = b"".join(encode_record(child) for child in rec.children)
    else:
        payload = bytes(rec.data)
    payload += b"\0" * ((-len(payload)) % 4)
    total_len = 8 + len(payload)
    return struct.pack("<I", total_len) + rec.tag + payload


def record_size(rec):
    return len(encode_record(rec))


def walk(records):
    for rec in records:
        yield rec
        if rec.children:
            yield from walk(rec.children)


def cstring(data):
    if not data:
        return None
    end = data.find(0)
    if end <= 0:
        return None
    chars = data[:end]
    if not all(32 <= c < 127 for c in chars):
        return None
    if any(data[end:]):
        return None
    return chars.decode("ascii")


def subs_params(rec):
    params = []
    for off in range(4, len(rec.data) - 3, 4):
        entry = rec.data[off : off + 4]
        params.append(
            {
                "index": (off - 4) // 4,
                "raw": bytes(entry).hex(" "),
                # Layout below is inferred from the consistent byte patterns;
                # the outer TLV structure is the part that is certain.
                "type": entry[0],
                "value": struct.unpack_from("<H", entry, 1)[0],
                "flag": entry[3],
            }
        )
    return params


def record_summary(rec):
    if rec.children is not None:
        return "container (%d record(s))" % len(rec.children)
    if rec.tag == b"SUBS" and len(rec.data) >= 4:
        subs_id = struct.unpack_from("<I", rec.data, 0)[0]
        return "id=0x%02x (%d), %d param(s)" % (
            subs_id,
            subs_id,
            len(subs_params(rec)),
        )
    text = cstring(rec.data)
    if text is not None:
        return '"%s"' % text
    if rec.tag in BOOL_TAGS and rec.data:
        return "%d (%s)" % (rec.data[0], "on" if rec.data[0] else "off")
    if len(rec.data) == 4:
        return "u32=0x%08x" % struct.unpack_from("<I", rec.data, 0)[0]
    return rec.data.hex(" ")


def record_to_dict(rec):
    item = {
        "offset": rec.offset,
        "length": record_size(rec),
        "tag": rec.tag.decode("ascii", "replace"),
    }
    if rec.children is not None:
        item["kind"] = "container"
        item["children"] = [record_to_dict(child) for child in rec.children]
    elif rec.tag == b"SUBS" and len(rec.data) >= 4:
        item["kind"] = "subs"
        item["subs_id"] = struct.unpack_from("<I", rec.data, 0)[0]
        item["params"] = subs_params(rec)
    else:
        text = cstring(rec.data)
        if text is not None:
            item["kind"] = "string"
            item["value"] = text
        elif rec.tag in BOOL_TAGS and rec.data:
            item["kind"] = "bool"
            item["value"] = rec.data[0]
        elif len(rec.data) == 4:
            item["kind"] = "u32"
            item["value"] = struct.unpack_from("<I", rec.data, 0)[0]
        else:
            item["kind"] = "bytes"
            item["value"] = rec.data.hex(" ")
        item["payload_hex"] = rec.data.hex(" ")
    return item


def select_record(records, tag, subs_id=None, occurrence=None):
    tag_bytes = tag.encode("ascii") if isinstance(tag, str) else tag
    matches = [rec for rec in walk(records) if rec.tag == tag_bytes]
    if subs_id is not None:
        matches = [
            rec
            for rec in matches
            if rec.tag == b"SUBS"
            and len(rec.data) >= 4
            and struct.unpack_from("<I", rec.data, 0)[0] == subs_id
        ]
    if not matches:
        raise FormatError("record %r not found" % tag)
    if occurrence is not None:
        if occurrence < 0 or occurrence >= len(matches):
            raise FormatError(
                "occurrence %d out of range (found %d)" % (occurrence, len(matches))
            )
        return matches[occurrence]
    if len(matches) > 1:
        detail = ", ".join(
            "0x%04x%s"
            % (
                rec.offset,
                (
                    " id=0x%02x" % struct.unpack_from("<I", rec.data, 0)[0]
                    if rec.tag == b"SUBS" and len(rec.data) >= 4
                    else ""
                ),
            )
            for rec in matches[:8]
        )
        raise FormatError(
            "%d matches for %r (%s); use --subs-id or --occurrence"
            % (len(matches), tag, detail)
        )
    return matches[0]


def parse_int(text):
    try:
        return int(text, 0)
    except ValueError:
        raise SystemExit("not an integer: %r" % text)


def parse_bool(text):
    lowered = text.lower()
    if lowered in ("on", "true", "yes", "enable", "enabled"):
        return 1
    if lowered in ("off", "false", "no", "disable", "disabled"):
        return 0
    return parse_int(text)


def parse_hex_bytes(text):
    cleaned = (
        text.replace("0x", "")
        .replace(" ", "")
        .replace(":", "")
        .replace("-", "")
        .replace(",", "")
    )
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        raise SystemExit("not a hex byte string: %r" % text)


def read_file(path):
    data = Path(path).read_bytes()
    if not data:
        raise FormatError("empty file")
    return data


def print_records(records, indent=0):
    prefix = "  " * indent
    for rec in records:
        print(
            "%s0x%04x  len=%3d  %-4s  %s"
            % (
                prefix,
                rec.offset,
                record_size(rec),
                rec.tag.decode("ascii", "replace"),
                record_summary(rec),
            )
        )
        if rec.children is not None:
            print_records(rec.children, indent + 1)


def print_record_detail(rec):
    size = record_size(rec)
    tag_off = rec.offset + 4
    payload_off = rec.offset + 8
    print("tag:         %s" % rec.tag.decode("ascii", "replace"))
    print("record:      0x%04x..0x%04x (%d bytes)" % (rec.offset, rec.offset + size - 1, size))
    print("length field: 0x%04x (value %d)" % (rec.offset, size))
    print("tag offset:  0x%04x" % tag_off)
    print("payload:     0x%04x..0x%04x (%d bytes)" % (payload_off, payload_off + len(rec.data) - 1, len(rec.data)))
    print("payload hex: %s" % rec.data.hex(" "))
    if rec.children is not None:
        print("children:")
        print_records(rec.children, 1)
        if rec.container_error:
            print("container parse warning: %s" % rec.container_error)
        return
    if rec.tag == b"SUBS" and len(rec.data) >= 4:
        subs_id = struct.unpack_from("<I", rec.data, 0)[0]
        print("subs id:     0x%02x (%d)" % (subs_id, subs_id))
        print("params (byte0=type, bytes1-2=u16 LE value, byte3=flag; inferred):")
        for param in subs_params(rec):
            print(
                "  [%d] %-11s type=0x%02x value=%d (0x%04x) flag=0x%02x"
                % (
                    param["index"],
                    param["raw"],
                    param["type"],
                    param["value"],
                    param["value"],
                    param["flag"],
                )
            )
        return
    text = cstring(rec.data)
    if text is not None:
        print("string:      \"%s\"" % text)
    elif rec.tag in BOOL_TAGS and rec.data:
        print("bool byte:   %d (%s)" % (rec.data[0], "on" if rec.data[0] else "off"))
        if len(rec.data) > 1:
            print("reserved:    %s" % rec.data[1:].hex(" "))
    elif len(rec.data) == 4:
        print("u32:         0x%08x (%d)" % (
            struct.unpack_from("<I", rec.data, 0)[0],
            struct.unpack_from("<I", rec.data, 0)[0],
        ))


def diff_summary(old, new):
    if old == new:
        print("no byte changes")
        return
    if len(old) == len(new):
        diffs = [i for i in range(len(old)) if old[i] != new[i]]
        shown = " ".join(
            "0x%04x:%02x->%02x" % (i, old[i], new[i]) for i in diffs[:16]
        )
        more = "" if len(diffs) <= 16 else " ..."
        print("%d byte(s) changed: %s%s" % (len(diffs), shown, more))
        return
    limit = min(len(old), len(new))
    prefix = 0
    while prefix < limit and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while suffix < limit - prefix and old[-1 - suffix] == new[-1 - suffix]:
        suffix += 1
    print(
        "size %d -> %d (%+d); common prefix %d byte(s), common suffix %d byte(s)"
        % (len(old), len(new), len(new) - len(old), prefix, suffix)
    )


def next_backup_path(path):
    candidate = path.with_name(path.name + ".bak")
    index = 1
    while candidate.exists():
        candidate = path.with_name("%s.bak.%d" % (path.name, index))
        index += 1
    return candidate


def save_and_report(args, src_path, old_blob, records):
    new_blob = b"".join(encode_record(rec) for rec in records)

    reparsed = parse_records(new_blob)
    normalized = b"".join(encode_record(rec) for rec in reparsed)
    if normalized != new_blob:
        raise FormatError("internal error: re-encoded data is not stable")

    if args.dry_run or (not args.output and not args.in_place):
        diff_summary(old_blob, new_blob)
        if not args.dry_run:
            print("dry run: file not written (use -o OUT or --in-place)")
        return

    if args.in_place and args.output:
        raise SystemExit("use either -o OUT or --in-place, not both")

    if args.in_place:
        if not args.no_backup:
            backup = next_backup_path(src_path)
            shutil.copy2(src_path, backup)
            print("backup: %s" % backup)
        dest = src_path
    else:
        dest = Path(args.output)
        if dest.resolve() == src_path.resolve():
            raise SystemExit("output is the input file; use --in-place instead")

    dest.write_bytes(new_blob)
    written = dest.read_bytes()
    if written != new_blob:
        raise FormatError("write verification failed: %s" % dest)
    parse_records(written)
    print("wrote: %s (%d bytes, sha256 %s)" % (
        dest,
        len(new_blob),
        hashlib.sha256(new_blob).hexdigest()[:16],
    ))
    diff_summary(old_blob, new_blob)


def add_write_args(parser):
    parser.add_argument("-o", "--output", help="write result to this file")
    parser.add_argument("--in-place", action="store_true", help="write back to the input file")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="with --in-place, do not create a .bak file",
    )
    parser.add_argument("--dry-run", action="store_true", help="show changes but do not write")


def add_select_args(parser):
    parser.add_argument("--subs-id", help="select the SUBS record with this id (e.g. 0x83)")
    parser.add_argument("--occurrence", type=int, help="select the Nth match (0-based)")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Read and safely edit ulogio /setting TLV files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  %(prog)s ulogio-203.bin list
  %(prog)s ulogio-203.bin get TELN
  %(prog)s ulogio-203.bin set TELN on -o telnet-on.bin
  %(prog)s ulogio-203.bin set TELN on --in-place
  %(prog)s ulogio-203.bin set-string ALGT ulogio_tlog2.txt -o out.bin
  %(prog)s ulogio-203.bin patch TELN 0 01 -o out.bin
  %(prog)s ulogio-203.bin verify
  %(prog)s ulogio-200.bin selftest
  %(prog)s ulogio-203.bin selftest
""",
    )
    parser.add_argument("file", help="input .bin file")
    sub = parser.add_subparsers(dest="cmd", required=True)

    listing = sub.add_parser("list", help="list records")
    listing.add_argument("--json", action="store_true", help="emit JSON")

    get = sub.add_parser("get", help="show one record")
    get.add_argument("tag")
    add_select_args(get)

    set_cmd = sub.add_parser("set", help="set a boolean/byte flag record (byte 0)")
    set_cmd.add_argument("tag")
    set_cmd.add_argument("value", help="on/off, or a number")
    add_select_args(set_cmd)
    add_write_args(set_cmd)

    set_string = sub.add_parser("set-string", help="replace a string record and fix its length")
    set_string.add_argument("tag")
    set_string.add_argument("value")
    set_string.add_argument(
        "--keep-size",
        action="store_true",
        help="keep the original payload size (pad with NUL; fail if too long)",
    )
    add_select_args(set_string)
    add_write_args(set_string)

    set_byte = sub.add_parser("set-byte", help="patch one payload byte")
    set_byte.add_argument("tag")
    set_byte.add_argument("offset", help="payload-relative offset")
    set_byte.add_argument("value")
    add_select_args(set_byte)
    add_write_args(set_byte)

    set_u32 = sub.add_parser("set-u32", help="patch one payload-relative u32")
    set_u32.add_argument("tag")
    set_u32.add_argument("index", help="payload-relative u32 index (0-based)")
    set_u32.add_argument("value")
    add_select_args(set_u32)
    add_write_args(set_u32)

    patch = sub.add_parser("patch", help="write raw hex bytes at a payload offset")
    patch.add_argument("tag")
    patch.add_argument("offset", help="payload-relative offset")
    patch.add_argument("hexbytes", help='e.g. "01" or "00 80 00 00"')
    add_select_args(patch)
    add_write_args(patch)

    sub.add_parser("verify", help="validate all records and length fields")
    sub.add_parser("selftest", help="verify parse -> encode is byte-identical")
    return parser


def cmd_verify(path):
    data = read_file(path)
    records = parse_records(data)
    for rec in walk(records):
        actual = read_u32(data, rec.offset)
        expected = record_size(rec)
        if actual != expected:
            raise FormatError(
                "length mismatch for %s at 0x%x: field=%d actual=%d"
                % (rec.tag.decode("ascii", "replace"), rec.offset, actual, expected)
            )
    blob = b"".join(encode_record(rec) for rec in records)
    if blob != data:
        raise FormatError("round-trip mismatch (file has unusual padding?)")
    count = sum(1 for _ in walk(records))
    print(
        "OK: %d top-level record(s), %d total, %d bytes, sha256 %s"
        % (
            len(records),
            count,
            len(data),
            hashlib.sha256(data).hexdigest()[:16],
        )
    )


def cmd_selftest(paths):
    for path in paths:
        data = read_file(path)
        records = parse_records(data)
        blob = b"".join(encode_record(rec) for rec in records)
        if blob != data:
            raise FormatError("round-trip mismatch: %s" % path)
        count = sum(1 for _ in walk(records))
        print(
            "OK: %s  %d top-level, %d total, %d bytes, sha256 %s"
            % (
                path,
                len(records),
                count,
                len(data),
                hashlib.sha256(data).hexdigest()[:16],
            )
        )


def main(argv=None):
    args = build_parser().parse_args(argv)
    path = Path(args.file)
    try:
        if args.cmd == "selftest":
            cmd_selftest([path])
            return 0
        if args.cmd == "verify":
            cmd_verify(path)
            return 0

        old_blob = read_file(path)
        records = parse_records(old_blob)

        if args.cmd == "list":
            if args.json:
                doc = {
                    "file": str(path),
                    "size": len(old_blob),
                    "sha256": hashlib.sha256(old_blob).hexdigest(),
                    "records": [record_to_dict(rec) for rec in records],
                }
                print(json.dumps(doc, indent=2, ensure_ascii=False))
            else:
                print("file: %s (%d bytes)" % (path, len(old_blob)))
                print_records(records)
            return 0

        subs_id = parse_int(args.subs_id) if getattr(args, "subs_id", None) else None
        occurrence = getattr(args, "occurrence", None)
        rec = select_record(records, args.tag, subs_id, occurrence)

        if args.cmd == "get":
            print_record_detail(rec)
            return 0

        if args.cmd == "set":
            if rec.children is not None:
                raise FormatError("%s is a container; use set-byte/patch" % args.tag)
            if not rec.data:
                rec.data = bytearray(b"\0")
            value = parse_bool(args.value)
            if not 0 <= value <= 255:
                raise SystemExit("value must fit in one byte")
            rec.data[0] = value
            print(
                "set %s byte 0 at 0x%04x to %d"
                % (rec.tag.decode("ascii", "replace"), rec.offset + 8, value)
            )

        elif args.cmd == "set-string":
            if rec.children is not None:
                raise FormatError("%s is a container" % args.tag)
            if rec.tag not in STRING_TAGS:
                raise FormatError(
                    "%s is not a known string record; refusing to guess" % args.tag
                )
            raw = args.value.encode("utf-8")
            if b"\0" in raw:
                raise FormatError("string must not contain NUL")
            new_data = raw + b"\0"
            if args.keep_size:
                if len(new_data) > len(rec.data):
                    raise FormatError(
                        "new string needs %d payload bytes, record has %d"
                        % (len(new_data), len(rec.data))
                    )
                new_data += b"\0" * (len(rec.data) - len(new_data))
            else:
                new_data += b"\0" * ((-len(new_data)) % 4)
            rec.data = bytearray(new_data)
            print(
                "set %s at 0x%04x to %r (payload %d bytes)"
                % (rec.tag.decode("ascii", "replace"), rec.offset, args.value, len(rec.data))
            )

        elif args.cmd == "set-byte":
            if rec.children is not None:
                raise FormatError("%s is a container" % args.tag)
            offset = parse_int(args.offset)
            value = parse_int(args.value)
            if not 0 <= offset < len(rec.data):
                raise FormatError("payload offset %d out of range (0..%d)" % (offset, len(rec.data) - 1))
            if not 0 <= value <= 255:
                raise SystemExit("value must fit in one byte")
            old = rec.data[offset]
            rec.data[offset] = value
            print(
                "patched %s payload[%d] at 0x%04x: 0x%02x -> 0x%02x"
                % (rec.tag.decode("ascii", "replace"), offset, rec.offset + 8 + offset, old, value)
            )

        elif args.cmd == "set-u32":
            if rec.children is not None:
                raise FormatError("%s is a container" % args.tag)
            index = parse_int(args.index)
            value = parse_int(args.value)
            if not 0 <= value <= 0xFFFFFFFF:
                raise SystemExit("value must fit in 32 bits")
            if index < 0 or (index + 1) * 4 > len(rec.data):
                raise FormatError("u32 index %d out of range" % index)
            old = read_u32(rec.data, index * 4)
            struct.pack_into("<I", rec.data, index * 4, value)
            print(
                "patched %s payload u32[%d] at 0x%04x: 0x%08x -> 0x%08x"
                % (rec.tag.decode("ascii", "replace"), index, rec.offset + 8 + index * 4, old, value)
            )

        elif args.cmd == "patch":
            if rec.children is not None:
                raise FormatError("%s is a container" % args.tag)
            offset = parse_int(args.offset)
            raw = parse_hex_bytes(args.hexbytes)
            if offset < 0 or offset + len(raw) > len(rec.data):
                raise FormatError("patch range out of payload")
            rec.data[offset : offset + len(raw)] = raw
            print(
                "patched %s payload at 0x%04x with %s"
                % (rec.tag.decode("ascii", "replace"), rec.offset + 8 + offset, raw.hex(" "))
            )

        save_and_report(args, path, old_blob, records)
        return 0

    except FormatError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
