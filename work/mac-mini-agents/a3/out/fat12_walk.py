#!/usr/bin/env python3
"""Walk a FAT12 image: full directory tree, LFN, start cluster, byte offset, size, md5.

Usage: python3 fat12_walk.py <image> [outdir]
"""
import hashlib
import json
import os
import struct
import sys

IMG = sys.argv[1] if len(sys.argv) > 1 else "nflasha3.bin"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(__file__))
data = open(IMG, "rb").read()

bps = struct.unpack_from("<H", data, 0x0B)[0]
spc = data[0x0D]
reserved = struct.unpack_from("<H", data, 0x0E)[0]
nfats = data[0x10]
root_entries = struct.unpack_from("<H", data, 0x11)[0]
total16 = struct.unpack_from("<H", data, 0x13)[0]
media = data[0x15]
spf = struct.unpack_from("<H", data, 0x16)[0]
total32 = struct.unpack_from("<I", data, 0x20)[0]
total = total16 or total32

fat_off = reserved * bps
root_off = fat_off + nfats * spf * bps
root_sectors = (root_entries * 32 + bps - 1) // bps
data_off = root_off + root_sectors * bps
cluster_size = bps * spc
nclusters = (total - (data_off // bps)) // spc
fat = data[fat_off:fat_off + spf * bps]


def fat_next(n):
    off = n + n // 2
    v = fat[off] | (fat[off + 1] << 8)
    return (v >> 4) & 0xFFF if n & 1 else v & 0xFFF


def chain(start, limit=None):
    out, seen, n = [], set(), start
    while 2 <= n < 0xFF8:
        if n in seen:
            out.append(("LOOP", n))
            break
        if limit is not None and len(out) >= limit:
            break
        seen.add(n)
        out.append(n)
        n = fat_next(n)
    return out


def cluster_off(n):
    return data_off + (n - 2) * cluster_size


def read_clusters(start, size=None):
    buf = bytearray()
    for n in chain(start):
        if isinstance(n, tuple):
            break
        buf += data[cluster_off(n):cluster_off(n) + cluster_size]
        if size is not None and len(buf) >= size:
            break
    return bytes(buf[:size]) if size is not None else bytes(buf)


def lfn_name(entries, short):
    # entries are stored preceding the SFN, highest ordinal first
    parts = []
    for e in sorted(entries, key=lambda x: x[0] & 0x3F):
        seq = e[0] & 0x3F
        if seq == 0:
            continue
        raw = e[1:11] + e[14:26] + e[28:32]
        chars = [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]
        for c in chars:
            if c in (0x0000, 0xFFFF):
                return "".join(parts)
            parts.append(chr(c))
    return "".join(parts) if parts else None


def parse_dir(buf, path, depth=0):
    items, lfn = [], []
    for i in range(0, len(buf), 32):
        e = buf[i:i + 32]
        if len(e) < 32 or e[0] == 0x00:
            break
        attr = e[11]
        if e[0] == 0xE5:       # deleted entry: drop pending LFN
            lfn = []
            continue
        if attr == 0x0F:       # LFN entry
            lfn.append(e)
            continue
        if attr & 0x08:        # volume label
            lfn = []
            continue
        base = e[0:8].rstrip(b" ").decode("cp437", "replace")
        ext = e[8:11].rstrip(b" ").decode("cp437", "replace")
        if base == "." or base == "..":
            lfn = []
            continue
        sfn = base + ("." + ext if ext else "")
        longname = lfn_name(lfn, sfn)
        lfn = []
        # NT case flags (0x0C) for 8.3 display
        if not longname and e[12] & 0x18:
            if e[12] & 0x08:
                base = base.lower()
            if e[12] & 0x10:
                ext = ext.lower()
            sfn = base + ("." + ext if ext else "")
        cluster = struct.unpack_from("<H", e, 26)[0]
        cluster_hi = struct.unpack_from("<H", e, 20)[0]
        if cluster_hi:
            cluster |= cluster_hi << 16
        size = struct.unpack_from("<I", e, 28)[0]
        ctime = struct.unpack_from("<H", e, 14)[0]
        cdate = struct.unpack_from("<H", e, 16)[0]
        wtime = struct.unpack_from("<H", e, 22)[0]
        wdate = struct.unpack_from("<H", e, 24)[0]

        def dosdate(d):
            if d == 0:
                return "-"
            return "%04d-%02d-%02d" % (1980 + (d >> 9), (d >> 5) & 0xF, d & 0x1F)

        def dostime(t):
            if t == 0:
                return "-"
            return "%02d:%02d:%02d" % (t >> 11, (t >> 5) & 0x3F, (t & 0x1F) * 2)

        is_dir = bool(attr & 0x10)
        item = {
            "path": path + "/" + (longname or sfn),
            "name": longname or sfn,
            "sfn": sfn,
            "lfn": longname,
            "dir": is_dir,
            "attr": attr,
            "start_cluster": cluster,
            "byte_offset": cluster_off(cluster) if cluster >= 2 else None,
            "size": size,
            "cluster_chain": [c for c in chain(cluster)] if cluster >= 2 else [],
            "wdate": dosdate(wdate),
            "wtime": dostime(wtime),
            "cdate": dosdate(cdate),
            "ctime": dostime(ctime),
            "md5": None,
            "sha1": None,
            "data": None,
        }
        if is_dir:
            if cluster >= 2:
                dpath = path + "/" + (longname or sfn)
                sub = read_clusters(cluster)
                item["children"] = parse_dir(sub, dpath, depth + 1)
            else:
                item["children"] = []
        else:
            content = read_clusters(cluster, size)
            item["data"] = content
            item["md5"] = hashlib.md5(content).hexdigest()
            item["sha1"] = hashlib.sha1(content).hexdigest()
            item["actual_bytes_read"] = len(content)
        items.append(item)
    return items


def walk(items, depth=0, lines=None, rows=None):
    lines = [] if lines is None else lines
    rows = [] if rows is None else rows
    for it in items:
        tag = "d" if it["dir"] else "-"
        size_s = "-" if it["dir"] else str(it["size"])
        off = it["byte_offset"]
        if off is None:
            off_s = "-"
        else:
            off_s = "0x%x(%d)" % (off, off)
        md5 = it["md5"] or "-"
        lfn = it["lfn"] or ""
        lines.append("%s%s %-40s clu=%-5s off=%-18s size=%-8s md5=%s%s" % (
            "  " * depth, tag, it["name"], it["start_cluster"], off_s, size_s, md5,
            ("  [LFN: %s; 8.3: %s]" % (lfn, it["sfn"])) if lfn else ""))
        rows.append({
            "path": it["path"],
            "type": "dir" if it["dir"] else "file",
            "long_name": it["lfn"] or "",
            "short_name": it["sfn"],
            "start_cluster": it["start_cluster"],
            "byte_offset": it["byte_offset"],
            "byte_offset_hex": ("0x%x" % it["byte_offset"]) if it["byte_offset"] is not None else "",
            "sector_offset": (it["byte_offset"] // bps) if it["byte_offset"] is not None else None,
            "size": it["size"] if not it["dir"] else None,
            "cluster_count": len(it["cluster_chain"]),
            "cluster_chain": it["cluster_chain"],
            "md5": it["md5"],
            "sha1": it["sha1"],
            "mtime": (it["wdate"] + " " + it["wtime"]) if it["wdate"] != "-" else "",
            "attr": it["attr"],
            "actual_bytes_read": it.get("actual_bytes_read"),
        })
        if it["dir"]:
            walk(it["children"], depth + 1, lines, rows)
    return lines, rows


root = data[root_off:root_off + root_sectors * bps]
tree = parse_dir(root, "")
lines, rows = walk(tree)

hdr = [
    "FAT12 image: %s" % os.path.basename(IMG),
    "  bytes-per-sector=%d  sectors-per-cluster=%d  cluster-size=%d" % (bps, spc, cluster_size),
    "  reserved=%d  fats=%d  sectors-per-fat=%d  root-entries=%d  total-sectors=%d  media=0x%02x" % (
        reserved, nfats, spf, root_entries, total, media),
    "  fat1-offset=0x%x  root-offset=0x%x  data-offset=0x%x (sector %d)  clusters=%d" % (
        fat_off, root_off, data_off, data_off // bps, nclusters),
    "  cluster N byte offset = 0x%x + (N-2)*%d" % (data_off, cluster_size),
    "",
]
summary = "files=%d dirs=%d total_bytes=%d" % (
    sum(1 for r in rows if r["type"] == "file"),
    sum(1 for r in rows if r["type"] == "dir"),
    sum(r["size"] or 0 for r in rows if r["type"] == "file"))
open(os.path.join(OUT, "tree.txt"), "w").write("\n".join(hdr + lines + ["", summary]) + "\n")
with open(os.path.join(OUT, "manifest.tsv"), "w") as f:
    cols = ("path", "type", "long_name", "short_name", "start_cluster",
            "byte_offset", "byte_offset_hex", "sector_offset", "size",
            "cluster_count", "md5", "sha1", "mtime", "attr", "actual_bytes_read")
    f.write("\t".join(cols) + "\n")
    for r in rows:
        f.write("\t".join("" if r[k] is None else str(r[k]) for k in cols) + "\n")
with open(os.path.join(OUT, "manifest.json"), "w") as f:
    json.dump({"image": os.path.basename(IMG),
               "bps": bps, "spc": spc, "cluster_size": cluster_size,
               "reserved": reserved, "fats": nfats, "sectors_per_fat": spf,
               "root_entries": root_entries, "total_sectors": total,
               "fat_off": fat_off, "root_off": root_off, "data_off": data_off,
               "clusters": nclusters, "summary": summary,
               "entries": rows}, f, indent=1)

print("\n".join(hdr + lines))
print("\n" + summary)
