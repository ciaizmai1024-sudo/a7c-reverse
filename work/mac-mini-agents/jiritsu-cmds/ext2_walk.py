#!/usr/bin/env python3
"""Minimal read-only ext2/ext3 image walker.

nflasha15.bin is an ext2 volume (block size 1KiB), not FAT, despite the
original task description.  This script walks it, prints/extracts files and
emits a manifest so every later finding can be reproduced byte-exactly.

Usage:
  python3 ext2_walk.py IMAGE                      # print tree + write manifest
  python3 ext2_walk.py IMAGE --out DIR            # manifest location
  python3 ext2_walk.py IMAGE --find REGEX         # only matching paths
  python3 ext2_walk.py IMAGE --extract /usr/lib/libJiritsu.so OUT
  python3 ext2_walk.py IMAGE --stat /usr/bin/sen.elf
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys

SB_OFF = 0x400


class Ext2:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        self.f.seek(SB_OFF)
        sb = self.f.read(1024)
        u16 = lambda o: struct.unpack_from("<H", sb, o)[0]
        u32 = lambda o: struct.unpack_from("<I", sb, o)[0]
        self.inodes_count = u32(0)
        self.blocks_count = u32(4)
        self.first_data_block = u32(0x14)
        self.block_size = 1024 << u32(0x18)
        self.blocks_per_group = u32(0x20)
        self.inodes_per_group = u32(0x28)
        self.magic = u16(0x38)
        self.inode_size = u16(0x58) if u16(0x4c) else 128
        self.first_ino = u32(0x54)
        self.feature_incompat = u32(0x60)
        self.has_filetype = bool(self.feature_incompat & 0x2)
        if self.magic != 0xEF53:
            raise SystemExit("not an ext2/3/4 image (magic=0x%04x)" % self.magic)
        self.gd_off = (self.first_data_block + 1) * self.block_size
        self.ngroups = (self.blocks_count - self.first_data_block
                        + self.blocks_per_group - 1) // self.blocks_per_group

    def read_block(self, n):
        self.f.seek(n * self.block_size)
        return self.f.read(self.block_size)

    def group_inode_table(self, g):
        self.f.seek(self.gd_off + g * 32 + 8)
        return struct.unpack("<I", self.f.read(4))[0]

    def inode(self, ino):
        g = (ino - 1) // self.inodes_per_group
        idx = (ino - 1) % self.inodes_per_group
        base = self.group_inode_table(g) * self.block_size
        self.f.seek(base + idx * self.inode_size)
        raw = self.f.read(self.inode_size)
        mode = struct.unpack_from("<H", raw, 0)[0]
        size = struct.unpack_from("<I", raw, 4)[0]
        blocks = struct.unpack_from("<I", raw, 28)[0]
        # ext2 i_dir_acl doubles as high 32 bits of size for regular files
        if size & 0x80000000:
            size |= struct.unpack_from("<I", raw, 108)[0] << 32
        ptrs = list(struct.unpack_from("<15I", raw, 40))
        return {
            "ino": ino, "mode": mode, "size": size, "blocks": blocks,
            "ptrs": ptrs,
            "type": {0x4000: "dir", 0x8000: "file", 0xA000: "symlink",
                     0x2000: "chr", 0x6000: "blk", 0x1000: "fifo",
                     0xC000: "sock"}.get(mode & 0xF000, "?"),
        }

    def _block_list(self, inode, nblocks):
        out = []
        ptrs = inode["ptrs"]
        out.extend(ptrs[:12])
        per = self.block_size // 4
        if nblocks > 12 and ptrs[12]:
            ind = struct.unpack("<%dI" % per, self.read_block(ptrs[12]))
            out.extend(ind)
        if nblocks > 12 + per and ptrs[13]:
            d = struct.unpack("<%dI" % per, self.read_block(ptrs[13]))
            for p in d:
                if p:
                    out.extend(struct.unpack("<%dI" % per, self.read_block(p)))
                else:
                    out.extend([0] * per)
        need3 = 12 + per + per * per
        if nblocks > need3 and ptrs[14]:
            d = struct.unpack("<%dI" % per, self.read_block(ptrs[14]))
            for p in d:
                if not p:
                    out.extend([0] * per * per)
                    continue
                d2 = struct.unpack("<%dI" % per, self.read_block(p))
                for q in d2:
                    if q:
                        out.extend(struct.unpack("<%dI" % per, self.read_block(q)))
                    else:
                        out.extend([0] * per)
        return out[:nblocks]

    def read_file(self, inode):
        if inode["type"] == "symlink" and inode["size"] < 60:
            return bytes(inode["ptrs"])[:inode["size"]]
        bs = self.block_size
        nblocks = (inode["size"] + bs - 1) // bs
        buf = bytearray()
        for n in self._block_list(inode, nblocks):
            if n == 0:
                buf += b"\0" * bs
            else:
                buf += self.read_block(n)
        return bytes(buf[:inode["size"]])

    def dirents(self, inode):
        data = self.read_file(inode)
        pos = 0
        out = []
        while pos + 8 <= len(data):
            ino, rec_len = struct.unpack_from("<IH", data, pos)
            name_len = data[pos + 6]
            ftype = data[pos + 7] if self.has_filetype else 0
            if rec_len < 8 or pos + rec_len > len(data):
                break
            if ino and name_len and name_len <= rec_len - 8:
                name = data[pos + 8:pos + 8 + name_len].decode("utf-8", "replace")
                out.append((name, ino, ftype))
            pos += rec_len
        return out

    def walk(self):
        root = self.inode(2)
        rows = []

        def rec(inode, path):
            rows.append({
                "path": path, "ino": inode["ino"], "type": inode["type"],
                "mode": "0%o" % inode["mode"], "size": inode["size"],
                "blocks": inode["blocks"], "md5": None, "sha256": None,
            })
            if inode["type"] == "dir":
                for name, ino, _ft in self.dirents(inode):
                    if name in (".", ".."):
                        continue
                    rec(self.inode(ino), path.rstrip("/") + "/" + name)

        rec(root, "")
        return rows

    def extract(self, path, out):
        rows = {r["path"]: r for r in self.walk()}
        if path not in rows:
            raise SystemExit("not found: " + path)
        ino = self.inode(rows[path]["ino"])
        data = self.read_file(ino)
        with open(out, "wb") as f:
            f.write(data)
        return data

    def close(self):
        self.f.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out", default=".")
    ap.add_argument("--find", default=None)
    ap.add_argument("--extract", nargs=2, metavar=("PATH", "OUT"))
    ap.add_argument("--stat", default=None)
    ap.add_argument("--no-hash", action="store_true")
    args = ap.parse_args()

    fs = Ext2(args.image)
    print("ext2: block=%d inodes=%d blocks=%d groups=%d inode_size=%d filetype=%s"
          % (fs.block_size, fs.inodes_count, fs.blocks_count, fs.ngroups,
             fs.inode_size, fs.has_filetype))

    if args.extract:
        data = fs.extract(args.extract[0], args.extract[1])
        print("extracted %s -> %s (%d bytes) sha256=%s"
              % (args.extract[0], args.extract[1], len(data),
                 hashlib.sha256(data).hexdigest()))
        return

    rows = fs.walk()
    if args.stat:
        r = [x for x in rows if x["path"] == args.stat]
        if not r:
            raise SystemExit("not found: " + args.stat)
        ino = fs.inode(r[0]["ino"])
        print(json.dumps(r[0], indent=2))
        print("pointers:", [hex(p) for p in ino["ptrs"]])
        return

    pat = re.compile(args.find) if args.find else None
    if not args.no_hash and not pat:
        for r in rows:
            if r["type"] == "file" and r["size"] <= 64 * 1024 * 1024:
                d = fs.read_file(fs.inode(r["ino"]))
                r["md5"] = hashlib.md5(d).hexdigest()
                r["sha256"] = hashlib.sha256(d).hexdigest()

    show = [r for r in rows if not pat or pat.search(r["path"])]
    for r in show:
        if r["type"] == "dir":
            print("%-70s dir" % r["path"])
        else:
            print("%-70s %-8s %10d %s" % (r["path"], r["type"], r["size"],
                                          r["md5"] or ""))

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "manifest.tsv"), "w") as f:
        cols = ("path", "type", "mode", "size", "ino", "blocks", "md5", "sha256")
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join("" if r[k] is None else str(r[k]) for k in cols) + "\n")
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump({"image": os.path.basename(args.image),
                   "block_size": fs.block_size,
                   "inodes_count": fs.inodes_count,
                   "blocks_count": fs.blocks_count,
                   "entries": rows}, f, indent=1)
    print("\nfiles=%d dirs=%d total_bytes=%d"
          % (sum(1 for r in rows if r["type"] == "file"),
             sum(1 for r in rows if r["type"] == "dir"),
             sum(r["size"] for r in rows if r["type"] == "file")))


if __name__ == "__main__":
    main()
