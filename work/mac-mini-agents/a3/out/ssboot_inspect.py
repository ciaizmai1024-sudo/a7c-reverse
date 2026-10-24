#!/usr/bin/env python3
"""Inspect the SABIN SSBOOT blobs inside nflasha3.bin.

Reads out/manifest.json (produced by fat12_walk.py) and the image, then:
  - dumps the first 512 bytes of ssboot.bin / ssboot_any.bin
  - decodes the common 0x7c-byte header alongside idt_cam.bin
  - checks for compression / container / executable magics
  - measures entropy, zero density, block similarity
  - writes out/ssboot_hex.txt and out/ssboot_analysis.json
"""
import collections
import difflib
import hashlib
import json
import math
import os
import struct
import sys

IMG = sys.argv[1] if len(sys.argv) > 1 else "nflasha3.bin"
OUT = os.path.dirname(os.path.abspath(__file__))
data = open(IMG, "rb").read()
manifest = json.load(open(os.path.join(OUT, "manifest.json")))
files = {e["path"].split("/")[-1]: e for e in manifest["entries"] if e["type"] == "file"}


def blob(name):
    e = files[name]
    return data[e["byte_offset"]:e["byte_offset"] + e["size"]]


sb = blob("ssboot.bin")
sa = blob("ssboot_any.bin")
idt = blob("idt_cam.bin")

MAGICS = {
    "gzip 1f8b08": bytes.fromhex("1f8b08"),
    "xz fd377a585a00": bytes.fromhex("fd377a585a00"),
    "bzip2 BZh": b"BZh",
    "lz4 04224d18": bytes.fromhex("04224d18"),
    "zstd 28b52ffd": bytes.fromhex("28b52ffd"),
    "lzo 894c5a4f": bytes.fromhex("894c5a4f"),
    "cramfs 45 3d cd 28": bytes.fromhex("453dcd28"),
    "squashfs hsqs": b"hsqs",
    "squashfs sqsh": b"sqsh",
    "ELF 7f454c46": b"\x7fELF",
    "uImage 27051956": bytes.fromhex("27051956"),
    "FIT d00dfeed": bytes.fromhex("d00dfeed"),
    "ARM zImage 016f2818": bytes.fromhex("18286f01"),
    "Android ANDROID!": b"ANDROID!",
    "B4 tag at +4": None,  # special-cased below
}


def entropy(b):
    if not b:
        return 0.0
    c = collections.Counter(b)
    n = len(b)
    return -sum((v / n) * math.log2(v / n) for v in c.values())


def magic_report(b):
    out = {}
    for name, m in MAGICS.items():
        if m is not None:
            pos = b.find(m)
            if pos != -1:
                out[name] = pos
    if len(b) >= 6 and b[4:6] == b"B4":
        out["B4 tag at +4"] = 4
    return out


def ascii_strings(b, minlen=4):
    import re
    return [m.group().decode("ascii") for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, b)]


def hexdump(b, length=512):
    lines = []
    for off in range(0, min(length, len(b)), 16):
        chunk = b[off:off + 16]
        hx = " ".join("%02x" % x for x in chunk)
        asc = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
        lines.append("%08x  %-47s  |%s|" % (off, hx, asc))
    return "\n".join(lines)


def header_fields(b):
    fields = []
    for off in range(0, 0x7C, 4):
        u32 = struct.unpack_from("<I", b, off)[0]
        u16a, u16b = struct.unpack_from("<HH", b, off)
        f32 = struct.unpack_from("<f", b, off)[0]
        fields.append({"offset": off, "u16_lo": u16a, "u16_hi": u16b,
                       "u32": u32, "u32_hex": "0x%08x" % u32,
                       "float": round(f32, 6) if abs(f32) < 1e6 else None})
    return fields


def block_similarity(b, starts, block=0x5E0):
    res = []
    for x, y in zip(starts, starts[1:]):
        bx, by = b[x:x + block], b[y:y + block]
        sm = difflib.SequenceMatcher(None, bx, by, autojunk=False)
        eq = sum(m.size for m in sm.get_matching_blocks())
        res.append({"a": x, "b": y, "equal_bytes": eq, "block": block,
                    "ratio": round(eq / block, 4)})
    return res


def seq_ratio(a, b):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    eq = sum(m.size for m in sm.get_matching_blocks())
    return {"equal_bytes": eq, "min_len": min(len(a), len(b)),
            "ratio_of_min": round(eq / min(len(a), len(b)), 4),
            "longest_run": max((m.size for m in sm.get_matching_blocks()), default=0)}


def common_prefix(a, b):
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n


report = {}
for name, b in [("ssboot.bin", sb), ("ssboot_any.bin", sa), ("idt_cam.bin", idt)]:
    report[name] = {
        "size": len(b),
        "md5": hashlib.md5(b).hexdigest(),
        "sha1": hashlib.sha1(b).hexdigest(),
        "entropy": round(entropy(b), 4),
        "byte0_count": b.count(0),
        "byteff_count": b.count(0xFF),
        "zero_pct": round(100.0 * b.count(0) / len(b), 2),
        "magnitudes": magic_report(b),
        "ascii_strings_min4": ascii_strings(b, 4)[:200],
        "header_first_0x7c": header_fields(b),
        "cluster_chain": files[name]["cluster_chain"],
        "start_cluster": files[name]["start_cluster"],
        "byte_offset": files[name]["byte_offset"],
    }

report["pairwise"] = {
    "ssboot_vs_any_common_prefix": common_prefix(sb, sa),
    "ssboot_vs_idt_common_prefix": common_prefix(sb, idt),
    "ssboot_payload_from_0x80_vs_any_0x7c": seq_ratio(sb[0x80:], sa[0x7C:]),
    "ssboot_payload_from_0x84_vs_idt_0x7c": seq_ratio(sb[0x84:], idt[0x7C:]),
}
starts = [0xEA0, 0x14D0, 0x1AB0, 0x2090]
sims = block_similarity(sb, starts)
report["ssboot_repeated_blocks"] = {"starts": starts, "pairs": sims}

hexout = []
for name, b in [("ssboot.bin", sb), ("ssboot_any.bin", sa)]:
    hexout.append("========== %s : first 512 bytes (md5 %s, size %d) ==========" % (
        name, hashlib.md5(b).hexdigest(), len(b)))
    hexout.append(hexdump(b, 512))
    hexout.append("")
hexout.append("========== 0x7C header fields: offset | ssboot u32 | ssboot_any u32 | idt_cam u32 ==========")
for i in range(0x7C // 4):
    fs = struct.unpack_from("<I", sb, i * 4)[0]
    fa = struct.unpack_from("<I", sa, i * 4)[0]
    fi = struct.unpack_from("<I", idt, i * 4)[0]
    extra = ""
    if struct.unpack_from("<f", sb, i * 4)[0] == struct.unpack_from("<f", sa, i * 4)[0] == 1.9375:
        extra = "  (float 1.9375)"
    hexout.append("  +0x%02x  %08x  %08x  %08x%s" % (i * 4, fs, fa, fi, extra))
open(os.path.join(OUT, "ssboot_hex.txt"), "w").write("\n".join(hexout) + "\n")
json.dump(report, open(os.path.join(OUT, "ssboot_analysis.json"), "w"), indent=1)

print("wrote ssboot_hex.txt and ssboot_analysis.json")
for name in ("ssboot.bin", "ssboot_any.bin", "idt_cam.bin"):
    r = report[name]
    print("%-14s size=%-7d md5=%s entropy=%.3f zero=%d%% magics=%s" % (
        name, r["size"], r["md5"], r["entropy"], r["zero_pct"], r["magnitudes"]))
print("common prefixes:", report["pairwise"])
print("ssboot repeated block starts:", [hex(x) for x in starts])
print("block equal ratios:", [p["ratio"] for p in sims])
print("printable strings >=8:", [s for s in report["ssboot.bin"]["ascii_strings_min4"] if len(s) >= 8][:20])
print("printable strings >=8 (any):", [s for s in report["ssboot_any.bin"]["ascii_strings_min4"] if len(s) >= 8][:20])
