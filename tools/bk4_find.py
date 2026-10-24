#!/usr/bin/env python3
# 来源：100.122.234.78 上 qoderclicn(-m DeepSeek-Flash) 子代理产出；主会话独立复核过表结构（条目表 0x10C/750×6→字段数组 0x12A0、sum(count)=30063 vs 容量 30064、内容区 0x2D340）与 info 里的 device/version/mode 字段。
"""Locate entries and fields in a BK4 camera settings image.

Layout (little-endian) -- see README.md for what is confirmed vs inferred:

  0x000  header
  0x10c  entry table: N * 6 bytes  {u16 count, u24 rec_start, u8 type}
  T      index array: M * 6 bytes  {u16 flags, u24 target, u8 size}
  C      content area: C = header[0x18], length = header[0x1c]

A type-0 entry owns the records [rec_start, rec_start+count).  Each record
describes one field at absolute file offset `target` with `size` bytes
(255 appears to mean variable length; sentinel is target 0xffffff + size 255).
A type-4 entry stores the content anchor address in its u24 field instead of
a record index.

Examples:
  python3 bk4_find.py CX88600_UC2.bin info
  python3 bk4_find.py CX88600_UC2.bin list --nonzero
  python3 bk4_find.py CX88600_UC2.bin entry 176
  python3 bk4_find.py BACKUP.BIN find ascii:DIRECT-USE1
  python3 bk4_find.py CX88600_UC2.bin find hex:0000ff0100
  python3 bk4_find.py CX88600_UC2.bin field --size 20
  python3 bk4_find.py CX88600_UC2.bin verify
"""

import argparse
import bisect
import os
import struct
import sys

TABLE_OFF = 0x10C
ENTRY_SIZE = 6
RECORD_SIZE = 6
SENTINEL_TARGET = 0xFFFFFF
SENTINEL_SIZE = 0xFF


def u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def u24(buf, off):
    return int.from_bytes(buf[off:off + 3], "little")


def u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def cstr(buf, off, size):
    raw = buf[off:off + size].split(b"\0", 1)[0]
    return raw.decode("utf-8", "replace")


def hexdump(data, base=0, width=16):
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"  {base + i:08x}  {hexpart:<{width * 3}}  {asc}")
    return "\n".join(lines)


class Entry:
    __slots__ = ("index", "count", "rec_start", "type")

    def __init__(self, index, count, rec_start, etype):
        self.index = index
        self.count = count
        self.rec_start = rec_start
        self.type = etype

    def record_range(self):
        return range(self.rec_start, self.rec_start + self.count)


class Record:
    __slots__ = ("index", "flags", "target", "size", "file_off")

    def __init__(self, index, flags, target, size, file_off):
        self.index = index
        self.flags = flags
        self.target = target
        self.size = size
        self.file_off = file_off

    @property
    def sentinel(self):
        return self.target == SENTINEL_TARGET and self.size == SENTINEL_SIZE


class Image:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as fh:
            self.data = fh.read()
        self.size = len(self.data)
        self._parse_header()
        self._parse_table()
        self._parse_records()
        self._build_owners()

    def _parse_header(self):
        d = self.data
        if len(d) < TABLE_OFF:
            raise ValueError("file too short to be a BK4 image")
        if d[0x0C:0x10] != b"BK4\0":
            raise ValueError(f"{self.path}: missing BK4 magic at 0x0c")
        self.phy_addr = u32(d, 0x00)
        self.marker = u32(d, 0x04)
        self.mode = u32(d, 0x08)
        self.entry_count = u32(d, 0x10)
        self.record_total = u32(d, 0x14)
        self.content_off = u32(d, 0x18)
        self.content_len = u32(d, 0x1C)
        self.checksum = u32(d, 0x20)
        self.field_24 = u32(d, 0x24)
        self.dirty = u32(d, 0x28)
        self.field_2c = u32(d, 0x2C)
        self.timestamp = d[0x38:0x40]
        self.version = cstr(d, 0x40, 19)
        self.device = cstr(d, 0xC0, 16)
        self.field_108 = u32(d, 0x108)
        self.table_off = TABLE_OFF
        self.table_end = TABLE_OFF + ENTRY_SIZE * self.entry_count
        self.index_off = self.table_end
        self.index_bytes = max(0, self.content_off - self.index_off)
        self.index_capacity = self.index_bytes // RECORD_SIZE

    def _parse_table(self):
        self.entries = []
        d = self.data
        for i in range(self.entry_count):
            off = TABLE_OFF + ENTRY_SIZE * i
            if off + ENTRY_SIZE > len(d):
                break
            self.entries.append(Entry(i, u16(d, off), u24(d, off + 2), d[off + 5]))

    def _parse_records(self):
        self.records = []
        d = self.data
        for i in range(self.index_capacity):
            off = self.index_off + RECORD_SIZE * i
            self.records.append(Record(i, u16(d, off), u24(d, off + 2), d[off + 5], off))

    def _build_owners(self):
        owners = [-1] * len(self.records)
        for e in self.entries:
            if e.type != 0:
                continue
            for rec in e.record_range():
                if 0 <= rec < len(owners):
                    owners[rec] = e.index
                elif rec >= len(owners):
                    break
        self.owners = owners

    # -- lookups ---------------------------------------------------------
    def entry(self, index):
        if not 0 <= index < len(self.entries):
            raise IndexError(f"entry index {index} out of range 0..{len(self.entries) - 1}")
        return self.entries[index]

    def entry_records(self, entry):
        out = []
        if entry.type != 0:
            return out
        for k in entry.record_range():
            if 0 <= k < len(self.records):
                out.append(self.records[k])
        return out

    def owner_of_record(self, rec_index):
        if 0 <= rec_index < len(self.owners):
            return self.owners[rec_index]
        return -1

    def owner_of_index_byte(self, abs_off):
        if not (self.index_off <= abs_off < self.index_off + self.index_capacity * RECORD_SIZE):
            return None
        rec_index = (abs_off - self.index_off) // RECORD_SIZE
        return rec_index, self.owner_of_record(rec_index)

    def records_covering(self, abs_off):
        hits = []
        for rec in self.records:
            if rec.sentinel or rec.size == 0:
                continue
            if rec.target <= abs_off < rec.target + rec.size:
                hits.append(rec)
        return hits

    def field_bytes(self, rec):
        if rec.target >= self.size:
            return b""
        return self.data[rec.target:min(rec.target + rec.size, self.size)]


# -- output helpers ------------------------------------------------------

def fmt_data(data, limit=32):
    shown = data[:limit]
    hexpart = shown.hex(" ") if shown else "-"
    if len(data) > limit:
        hexpart += f" ... ({len(data)} bytes)"
    asc = "".join(chr(b) if 32 <= b < 127 else "." for b in shown)
    return f"{hexpart}  |{asc}|"


def print_header(img):
    print(f"file        : {img.path} ({img.size} bytes)")
    print(f"device      : {img.device}")
    print(f"version     : {img.version}")
    print(f"mode        : {img.mode}  (0=official/standard, 1=camera backup)")
    print(f"phy addr    : 0x{img.phy_addr:08x}   marker 0x{img.marker:08x}")
    print(f"dirty       : {img.dirty}   timestamp {img.timestamp.hex(' ')}")
    print(f"checksum?   : 0x{img.checksum:08x}   0x24={img.field_24}  0x2c=0x{img.field_2c:x}  0x108={img.field_108}")
    print(f"entries     : {img.entry_count}")
    print(f"record total: {img.record_total}  (sum of entry counts)")
    print(f"table       : 0x{img.table_off:x} .. 0x{img.table_end:x}  ({img.entry_count} * 6)")
    print(f"index array : 0x{img.index_off:x} .. 0x{img.content_off:x}  "
          f"({img.index_bytes} bytes, {img.index_capacity} records)")
    print(f"content     : 0x{img.content_off:x} .. 0x{img.content_off + img.content_len:x}  "
          f"({img.content_len} bytes)")
    print(f"size check  : content_off + content_len = "
          f"0x{img.content_off + img.content_len:x} "
          f"({'OK' if img.content_off + img.content_len == img.size else 'MISMATCH'})")


def cmd_info(img, args):
    print_header(img)
    nonzero = [e for e in img.entries if e.count]
    print(f"non-empty   : {len(nonzero)} / {img.entry_count}")
    print(f"max count   : {max((e.count for e in img.entries), default=0)}")
    print(f"sentinels   : {sum(1 for r in img.records if r.sentinel)}")
    print(f"size==20    : {sum(1 for r in img.records if r.size == 20 and not r.sentinel)} fields")
    anchors = [e for e in img.entries if e.type != 0]
    for e in anchors:
        print(f"type-{e.type} anchor: entry {e.index} address 0x{e.rec_start:x}")


def cmd_list(img, args):
    print(f"{'idx':>4} {'count':>6} {'rec_start':>9} {'bytes':>6} {'type':>4}  "
          f"{'target range':<24} first field")
    shown = 0
    for e in img.entries:
        if args.nonzero and not e.count:
            continue
        if args.type is not None and e.type != args.type:
            continue
        if args.min_count is not None and e.count < args.min_count:
            continue
        if args.max_count is not None and e.count > args.max_count:
            continue
        if e.type != 0:
            print(f"{e.index:>4} {e.count:>6} 0x{e.rec_start:07x} {e.count * 6:>6} {e.type:>4}  "
                  f"{'content anchor':<24} -")
            shown += 1
            continue
        recs = img.entry_records(e)
        if recs:
            first = recs[0]
            tmin = min(r.target for r in recs)
            tmax = max(r.target for r in recs)
            tgt = f"0x{tmin:06x}..0x{tmax:06x}"
            preview = fmt_data(img.field_bytes(first), 12)
        else:
            tgt = "-"
            preview = "-"
        print(f"{e.index:>4} {e.count:>6} {e.rec_start:>9} {e.count * 6:>6} {e.type:>4}  "
              f"{tgt:<24} {preview}")
        shown += 1
        if args.limit and shown >= args.limit:
            print(f"... stopped after {shown} rows (--limit)")
            break


def cmd_entry(img, args):
    e = img.entry(args.index)
    print(f"entry {e.index}: count={e.count} rec_start={e.rec_start} type={e.type}")
    if e.type != 0:
        addr = e.rec_start
        print(f"content anchor address: 0x{addr:x}")
        print(hexdump(img.data[addr:addr + 64], addr))
        return
    print(f"record range: {e.rec_start}..{e.rec_start + e.count - 1} "
          f"({e.count * 6} bytes of index)")
    if e.count == 0:
        print("(empty entry)")
        return
    recs = img.entry_records(e)
    if not recs:
        print("(no records inside the index array)")
        return
    limit = args.max_records if args.max_records is not None else len(recs)
    for rec in recs[:limit]:
        data = img.field_bytes(rec)
        if rec.sentinel:
            desc = "SENTINEL"
        else:
            desc = fmt_data(data, args.max_bytes) if args.follow else f"target 0x{rec.target:x} size {rec.size}"
        print(f"  rec {rec.index:>5} idx@0x{rec.file_off:06x} flags=0x{rec.flags:04x} "
              f"target=0x{rec.target:06x} size={rec.size:>3}  {desc}")
    if limit < len(recs):
        print(f"  ... {len(recs) - limit} more records (--max-records)")
    if args.raw:
        print("raw index window:")
        start = img.index_off + e.rec_start * RECORD_SIZE
        print(hexdump(img.data[start:start + e.count * RECORD_SIZE], start))


def cmd_field(img, args):
    print(f"{'rec':>6} {'entry':>5} {'flags':>6} {'target':>9} {'size':>4}  data")
    shown = 0
    for rec in img.records:
        if args.size is not None and rec.size != args.size:
            continue
        if args.entry is not None:
            owner = img.owner_of_record(rec.index)
            if owner != args.entry:
                continue
        if args.zero and any(img.field_bytes(rec)):
            continue
        if args.nonzero and not any(img.field_bytes(rec)):
            continue
        owner = img.owner_of_record(rec.index)
        data = img.field_bytes(rec)
        desc = "SENTINEL" if rec.sentinel else fmt_data(data, args.max_bytes)
        print(f"{rec.index:>6} {owner:>5} {rec.flags:>#6x} {rec.target:>#9x} {rec.size:>4}  {desc}")
        shown += 1
        if args.limit and shown >= args.limit:
            print(f"... stopped after {shown} rows (--limit)")
            break
    if not shown:
        print("(no matching records)")


def parse_pattern(text):
    if text.startswith("hex:"):
        return bytes.fromhex(text[4:].replace(" ", ""))
    if text.startswith("ascii:") or text.startswith("str:"):
        return text.split(":", 1)[1].encode("utf-8")
    stripped = text.replace(" ", "")
    if stripped.startswith("0x"):
        stripped = stripped[2:]
    if stripped and len(stripped) % 2 == 0:
        try:
            return bytes.fromhex(stripped)
        except ValueError:
            pass
    return text.encode("utf-8")


def cmd_find(img, args):
    needle = parse_pattern(args.pattern)
    if not needle:
        raise SystemExit("empty search pattern")
    d = img.data
    hits = []
    start = 0
    while True:
        pos = d.find(needle, start)
        if pos < 0:
            break
        hits.append(pos)
        start = pos + 1
        if args.limit and len(hits) >= args.limit:
            break
    if not hits:
        print(f"not found: {args.pattern!r} ({needle.hex(' ')})")
        return 1

    print(f"pattern: {args.pattern!r}  bytes: {needle.hex(' ')}  hits: {len(hits)}")
    for pos in hits:
        print(f"\nhit at 0x{pos:x}")
        if args.context:
            lo = max(0, pos - args.context)
            print(hexdump(d[lo:pos + len(needle) + args.context], lo))

        if pos < img.table_off:
            print("  region: header")
        elif pos < img.table_end:
            idx = (pos - img.table_off) // ENTRY_SIZE
            e = img.entry(idx)
            print(f"  region: entry table -> entry {idx} (count={e.count}, "
                  f"rec_start={e.rec_start}, type={e.type})")
            if args.entry is not None and idx != args.entry:
                continue
            continue
        elif pos < img.index_off + img.index_capacity * RECORD_SIZE:
            rec_index, owner = img.owner_of_index_byte(pos)
            rec = img.records[rec_index]
            print(f"  region: index array -> record {rec_index}, owner entry {owner}, "
                  f"record flags=0x{rec.flags:04x} target=0x{rec.target:x} size={rec.size}")
            if args.entry is not None and owner != args.entry:
                continue
            continue
        elif pos < img.content_off:
            print("  region: padding between index array and content")
            continue
        elif pos < img.content_off + img.content_len:
            print("  region: content area")
            covering = img.records_covering(pos)
            if covering:
                for rec in covering:
                    owner = img.owner_of_record(rec.index)
                    print(f"  -> field rec {rec.index}, entry {owner}, target 0x{rec.target:x}, "
                          f"size {rec.size}, flags 0x{rec.flags:04x}")
                    if args.entry is not None and owner != args.entry:
                        continue
            else:
                print("  -> no index record covers this offset (unindexed data)")
            continue
        else:
            print("  region: beyond declared content")
    return 0


def cmd_verify(img, args):
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))
        ok = ok and cond

    def warn(label, cond, detail=""):
        print(f"[{'PASS' if cond else 'WARN'}] {label}" + (f"  ({detail})" if detail else ""))

    check("BK4 magic", img.data[0x0C:0x10] == b"BK4\0")
    check("content end == file size",
          img.content_off + img.content_len == img.size,
          f"0x{img.content_off + img.content_len:x} vs 0x{img.size:x}")
    check("table ends at index start", img.table_off + ENTRY_SIZE * img.entry_count == img.index_off)
    total = sum(e.count for e in img.entries if e.type == 0)
    check("sum(count) == header[0x14]", total == img.record_total,
          f"{total} vs {img.record_total}")
    warn("sum(count) fits index array", total <= img.index_capacity,
         f"{total} records vs {img.index_capacity} available"
         + ("" if total <= img.index_capacity else
            " -- the last entries point past the index array into the content header"))
    anchors = [e for e in img.entries if e.type == 4]
    check("two type-4 anchors", len(anchors) == 2, f"got {len(anchors)}")
    if len(anchors) == 2:
        check("anchor[0] == content_off", anchors[0].rec_start == img.content_off,
              f"0x{anchors[0].rec_start:x}")
        check("anchor[1] == content_off + 4", anchors[1].rec_start == img.content_off + 4,
              f"0x{anchors[1].rec_start:x}")
    live = [r for r in img.records if not r.sentinel and r.size > 0]
    in_content = sum(1 for r in live
                     if img.content_off <= r.target < img.content_off + img.content_len)
    check("all live targets inside content", in_content == len(live),
          f"{in_content}/{len(live)}")
    print(f"records used by entries: {total} of {img.index_capacity} in the index array")
    print(f"size-20 fields         : {sum(1 for r in img.records if r.size == 20 and not r.sentinel)}")
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="BK4 settings image entry locator")
    parser.add_argument("image", help="BK4 image file")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="show header and region layout")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("list", help="list entries")
    p.add_argument("--nonzero", action="store_true", help="only entries with records")
    p.add_argument("--type", type=int, help="filter by entry type")
    p.add_argument("--min-count", type=int)
    p.add_argument("--max-count", type=int)
    p.add_argument("--limit", type=int, help="max rows")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("entry", help="dump one entry and its fields")
    p.add_argument("index", type=int)
    p.add_argument("--max-records", type=int)
    p.add_argument("--max-bytes", type=int, default=32)
    p.add_argument("--no-follow", dest="follow", action="store_false",
                   help="do not print target data")
    p.add_argument("--raw", action="store_true", help="hexdump the raw index window")
    p.set_defaults(func=cmd_entry, follow=True)

    p = sub.add_parser("find", help="locate an entry by content")
    p.add_argument("pattern", help="hex:.. / ascii:.. / raw hex / plain text")
    p.add_argument("--entry", type=int, help="only report hits owned by this entry")
    p.add_argument("--limit", type=int, default=20, help="max hits (default 20)")
    p.add_argument("--context", type=int, default=0, help="bytes of context to hexdump")
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("field", help="list index records / fields")
    p.add_argument("--entry", type=int)
    p.add_argument("--size", type=int)
    p.add_argument("--zero", action="store_true", help="only all-zero fields")
    p.add_argument("--nonzero", action="store_true", help="only non-zero fields")
    p.add_argument("--max-bytes", type=int, default=24)
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_field)

    p = sub.add_parser("verify", help="check layout invariants")
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    if not os.path.isfile(args.image):
        raise SystemExit(f"no such file: {args.image}")
    try:
        img = Image(args.image)
    except ValueError as exc:
        raise SystemExit(str(exc))
    return args.func(img, args) or 0


if __name__ == "__main__":
    sys.exit(main())
