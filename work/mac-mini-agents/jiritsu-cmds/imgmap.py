#!/usr/bin/env python3
"""Map a physical byte offset inside nflasha15.bin to the ext2 file that owns it.

Used to prove which module implements a given command table / string without
trusting offsets by eye.

Usage:
  python3 imgmap.py IMAGE OFFSET [OFFSET...]
  python3 imgmap.py IMAGE --find 'regex'   # locate string then map it
"""
import re
import sys

from ext2_walk import Ext2


def build_map(fs):
    """Return dict block_no -> (path, file_offset_of_block, file_size)."""
    rows = fs.walk()
    m = {}
    for r in rows:
        if r["type"] not in ("file",):
            continue
        ino = fs.inode(r["ino"])
        if ino["size"] == 0:
            continue
        nb = (ino["size"] + fs.block_size - 1) // fs.block_size
        try:
            blocks = fs._block_list(ino, nb)
        except Exception:
            continue
        for i, b in enumerate(blocks):
            if b and b not in m:
                m[b] = (r["path"], i * fs.block_size, r["size"])
    return m


def main():
    img = sys.argv[1]
    fs = Ext2(img)
    m = build_map(fs)
    data = open(img, "rb").read()
    args = sys.argv[2:]
    if args and args[0] == "--find":
        pat = re.compile(args[1].encode())
        offs = [mt.start() for mt in pat.finditer(data)]
    else:
        offs = [int(x, 0) for x in args]
    for off in offs:
        blk = off // fs.block_size
        if blk in m:
            path, fbase, size = m[blk]
            foff = fbase + (off - blk * fs.block_size)
            print("0x%08x -> %s +0x%x (file size %d)" % (off, path, foff, size))
        else:
            print("0x%08x -> <metadata/unused block %d>" % (off, blk))
    fs.close()


if __name__ == "__main__":
    main()
