#!/usr/bin/env python3
# mk_nflasha_ptable.py — write a Sony ALFReD nflasha partition table into an eMMC image.
#
# Empirical basis (Round 8, QEMU trace of hw/sd/sd.c sd_blk_read):
#   emmc.ko (ALFReD v161102p2) reads the partition table from the eMMC USER area
#   at byte offset 0x400000, in 512-byte chunks 0x400000..0x400E00 (8 reads),
#   then re-reads 0x400000. The loaded 4 KiB buffer is validated in
#   emmc_blk_plat_probe_post (emmc.ko .text 0x7eb0..):
#       buf[0x000]==buf[0x200] && buf[0x004]==buf[0x204] && buf[0x008]==buf[0x208]
#   (i.e. header {magic,version,n_partition} duplicated at +0x000 and +0x200).
#   Partition entries are walked as 16-byte slots at table_base+0x40+16*i
#   (disassembly reads [r7,#0x20]=start_bytes,[r7,#0x24]=size_bytes,[r7,#0x28]=type,
#    [r7,#0x2c]=flag with r7 = base+0x20+16*i), count = buf[0x008].
#   start/size are BYTE offsets on the device (sanity-checked for 512B alignment
#   via `lsls #23`, converted with lsr #9 to sectors).
#   type: 0=raw,1=vfat,2=WBI(warm boot),3=LZP(compressed) — from type cmp #2/#3
#   paths (emmc_register_wbi / emmc_register_lzp). flag 0xFFFFFFFF = active.
#
# NOTE (honesty): magic VALUE, version semantics, n_partition cap, and whether
# bytes 0x400..0xFFF hold a CRC/backup are NOT confirmed (closed-source blob);
# header field ORDER is taken from dump_ptbl_info string order
# (ptbl->magic, ptbl->version, ptbl->n_partition). Magic is a guess ("NPARTABL").
#
# usage: mk_nflasha_ptable.py <partinf.conf> <in.img> <out.img>
import struct, sys

PTBL_OFF = 0x400000
MAGIC = 0x4C415450  # "PTAL" LE spelling aside, value arbitrary-but-stable
VERSION = 1

def parse(p):
    ents = []
    for line in open(p, "rb"):
        line = line.decode("latin1")
        line = line.strip()
        if line.startswith('0x'):
            a = [int(x, 16) for x in line.split(',')]
            ents.append(tuple(a))
    return ents

def main():
    conf, src, dst = sys.argv[1:4]
    ents = parse(conf)
    img = bytearray(open(src, 'rb').read())
    hdr = struct.pack('<III', MAGIC, VERSION, len(ents))
    tbl = bytearray(0x1000)
    tbl[0x0:0x0+12] = hdr            # header copy A
    tbl[0x200:0x200+12] = hdr        # header copy B (validity pair)
    for i, (st, sz, ty, fl) in enumerate(ents):
        struct.pack_into('<IIII', tbl, 0x40 + 16*i, st, sz, ty, fl)
    assert PTBL_OFF + len(tbl) <= len(img), 'image too small'
    img[PTBL_OFF:PTBL_OFF+len(tbl)] = tbl
    open(dst, 'wb').write(img)
    print('wrote %d entries at %#x to %s' % (len(ents), PTBL_OFF, dst))

if __name__ == '__main__':
    main()
