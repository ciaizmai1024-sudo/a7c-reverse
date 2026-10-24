#!/usr/bin/env python3
"""Minimal read-only ext2 (rev0/rev1, no extents) walker/extractor.

nflasha15.bin is ext2, not FAT: this replaces the planned fat12_walk.py.
Only needs Python 3 stdlib.

Usage:
  ./ext2_walk.py IMAGE ls [PATH]                 list a directory
  ./ext2_walk.py IMAGE find NAME                 recursive name search
  ./ext2_walk.py IMAGE dump PATH OUT             extract one file
  ./ext2_walk.py IMAGE dumpall OUTDIR [PREFIX]   extract everything under PREFIX
"""
import os
import struct
import sys

BLOCK = 1024


class Ext2:
    def __init__(self, path):
        self.f = open(path, "rb")
        self.f.seek(1024)
        sb = self.f.read(1024)
        u16 = lambda o: struct.unpack_from("<H", sb, o)[0]
        u32 = lambda o: struct.unpack_from("<I", sb, o)[0]
        assert u16(56) == 0xEF53, "not ext2"
        self.inodes_count = u32(0)
        self.blocks_count = u32(4)
        self.first_data_block = u32(20)
        self.block_size = 1024 << u32(24)
        self.blocks_per_group = u32(32)
        self.inodes_per_group = u32(40)
        self.rev = u16(76)
        self.inode_size = u16(88) if self.rev >= 1 else 128
        self.incompat = u32(96)
        if self.incompat & 0x40:
            raise SystemExit("ext4 extents unsupported")
        self.groups = (self.blocks_count - self.first_data_block +
                       self.blocks_per_group - 1) // self.blocks_per_group
        gdt_block = self.first_data_block + 1
        self.gd = []
        self.f.seek(gdt_block * self.block_size)
        raw = self.f.read(self.groups * 32)
        for g in range(self.groups):
            d = raw[g * 32:(g + 1) * 32]
            self.gd.append({
                "block_bitmap": struct.unpack_from("<I", d, 0)[0],
                "inode_bitmap": struct.unpack_from("<I", d, 4)[0],
                "inode_table": struct.unpack_from("<I", d, 8)[0],
            })

    def _read_block(self, n):
        self.f.seek(n * self.block_size)
        return self.f.read(self.block_size)

    def inode(self, ino):
        g = (ino - 1) // self.inodes_per_group
        idx = (ino - 1) % self.inodes_per_group
        off = self.gd[g]["inode_table"] * self.block_size + idx * self.inode_size
        self.f.seek(off)
        d = self.f.read(self.inode_size)
        return {
            "ino": ino,
            "mode": struct.unpack_from("<H", d, 0)[0],
            "size": struct.unpack_from("<I", d, 4)[0],
            "mtime": struct.unpack_from("<I", d, 16)[0],
            "blocks": struct.unpack_from("<15I", d, 40),
        }

    def isdir(self, ino):
        return (ino["mode"] & 0xF000) == 0x4000

    def isfile(self, ino):
        return (ino["mode"] & 0xF000) == 0x8000

    def readlink(self, ino):
        if not ino["blocks"][0]:
            return ""
        return self.f.read(self.block_size)[:ino["size"]].decode("utf-8", "replace")

    def data(self, ino):
        bs = self.block_size
        blk = ino["blocks"]
        out = bytearray()
        count = (ino["size"] + bs - 1) // bs

        def emit(b):
            out.extend(self._read_block(b))

        def walk_indirect(start, level, remaining):
            # level 1: pointers to data blocks; level 2: to level-1, etc.
            if remaining <= 0:
                return
            ptrs = struct.unpack("<%dI" % (bs // 4), self._read_block(start))
            per = len(ptrs)
            for p in ptrs:
                if remaining <= 0:
                    return
                if p == 0:
                    # sparse hole: count one block worth (only valid at data level)
                    if level == 1:
                        out.extend(b"\0" * bs)
                        remaining -= 1
                    continue
                if level == 1:
                    emit(p)
                    remaining -= 1
                else:
                    walk_indirect(p, level - 1, remaining)
                    # recompute remaining conservatively from out length
                    remaining = count * bs - len(out)
                    if remaining <= 0:
                        return

        for b in blk[:12]:
            if count <= 0:
                break
            if b == 0:
                out.extend(b"\0" * bs)
            else:
                emit(b)
            count -= 1
            if len(out) >= ino["size"]:
                break
        if count > 0 and blk[12]:
            walk_indirect(blk[12], 1, count)
        count2 = (ino["size"] + bs - 1) // bs - min(12, (ino["size"] + bs - 1) // bs)
        if count2 > 0 and len(out) < ino["size"]:
            # double indirect
            need = (ino["size"] - len(out) + bs - 1) // bs
            walk_indirect(blk[13], 2, need) if blk[13] else None
        if len(out) < ino["size"] and blk[14]:
            need = (ino["size"] - len(out) + bs - 1) // bs
            walk_indirect(blk[14], 3, need)
        return bytes(out[:ino["size"]])

    def listdir(self, ino):
        data = self.data(ino)
        entries = []
        off = 0
        while off + 8 <= len(data):
            ino_n, rec_len, name_len = struct.unpack_from("<IHB", data, off)
            ftype = data[off + 7] if self.rev >= 1 else 0
            if rec_len < 8 or off + rec_len > len(data):
                break
            name = data[off + 8:off + 8 + name_len].decode("utf-8", "replace")
            if ino_n and name not in (".", ".."):
                entries.append((ino_n, name, ftype))
            off += rec_len
        return entries

    def lookup(self, path):
        cur = 2
        for part in [p for p in path.split("/") if p and p != "."]:
            ent = dict((n, i) for i, n, _ in self.listdir(self.inode(cur)))
            if part not in ent:
                return None
            cur = ent[part]
        return cur


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    fs = Ext2(sys.argv[1])
    cmd = sys.argv[2]
    if cmd == "ls":
        path = sys.argv[3] if len(sys.argv) > 3 else "/"
        ino = fs.lookup(path)
        if ino is None:
            raise SystemExit("no such path: " + path)
        if not fs.isdir(fs.inode(ino)):
            print(path)
            return
        for ino_n, name, ft in sorted(fs.listdir(fs.inode(ino)), key=lambda e: e[1].lower()):
            i = fs.inode(ino_n)
            if fs.isdir(i):
                kind = "d"
            elif (i["mode"] & 0xF000) == 0xA000:
                kind = "l"
            else:
                kind = "f"
            print("%s %10d %s%s" % (kind, i["size"], name,
                                     " -> " + fs.readlink(i) if kind == "l" else ""))
    elif cmd == "find":
        needle = sys.argv[3].lower()

        def rec(ino, path):
            for ino_n, name, _ in fs.listdir(fs.inode(ino)):
                p = path.rstrip("/") + "/" + name
                i = fs.inode(ino_n)
                if needle in name.lower():
                    print("%10d %s" % (i["size"], p))
                if fs.isdir(i):
                    rec(ino_n, p)

        rec(2, "")
    elif cmd == "dump":
        if len(sys.argv) < 5:
            raise SystemExit("dump PATH OUT")
        ino = fs.lookup(sys.argv[3])
        if ino is None:
            raise SystemExit("no such path: " + sys.argv[3])
        i = fs.inode(ino)
        if not fs.isfile(i):
            raise SystemExit("not a regular file: " + sys.argv[3])
        data = fs.data(i)
        out = sys.argv[4]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "wb") as f:
            f.write(data)
        print("wrote %s (%d bytes)" % (out, len(data)))
    elif cmd == "dumpall":
        outdir = sys.argv[3]
        prefix = sys.argv[4] if len(sys.argv) > 4 else ""

        def rec(ino, path):
            for ino_n, name, _ in fs.listdir(fs.inode(ino)):
                p = path.rstrip("/") + "/" + name
                i = fs.inode(ino_n)
                if fs.isdir(i):
                    rec(ino_n, p)
                elif fs.isfile(i) and p.startswith(prefix):
                    dst = os.path.join(outdir, p.lstrip("/"))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, "wb") as f:
                        f.write(fs.data(i))

        rec(2, "")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
