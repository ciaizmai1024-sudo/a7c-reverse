#!/usr/bin/env python3
# mk_nflasha_ptable_r9.py — Round 9: definitive Sony ALFReD nflasha partition table writer.
#
# CONFIRMED (disassembly of emmc.ko .init.text emmc_blk_plat_init @+0x678..0x69c,
# stores into kmalloc(0x218) ptbl_info struct; no DWARF present, but constants are
# literal pool words with NO relocations, so they are values not pointers):
#   ptbl_info layout:
#     +0x000 : 512-byte TABLE BUFFER (read from device; entries live here)
#     +0x200 : ptbl_magic   = 0x36343238 = ASCII "8246"
#     +0x204 : ptbl_version = 0x30302e31 = ASCII "1.00"
#     +0x208 : ptbl_part_max = 30
#     +0x20c : ptbl_sz_bytes = 512         (BUG_ON != 512 in probe_post)
#     +0x210 : ptbl_in_sector (set to 0x2000-... see below; driver probes LBA 0)
#     +0x214 : ptbl_in_part = 0 (USER partition; driver never issues a
#              PARTITION_CONFIG CMD6, verified by sd.c trace Round 9)
#   Validation in emmc_blk_plat_probe_post (.text 0x7eb0):
#     buf[0x00]==buf[0x200] (magic), buf[4]==buf[0x204] (version),
#     buf[8] <= buf[0x208] (n_partition <= part_max) else "partition table invalid".
#   Entries (.text 0x7f00 loop, i < buf[8]):
#     buf + 0x20 + 16*i : { u32 start_bytes; u32 size_bytes; u32 type; u32 flag }
#     flag bit0 = active; 512-byte alignment checked (lsls #23 == 0);
#     start+size checked vs capacity; type==2 => WBI (warm boot), type==3 => LZP.
#   hdr is 0x20 bytes: magic,version,n_partition,+0x0C..0x1F padding (zeros OK).
#   0x20 + 30*16 = 0x200 exactly -> table is exactly 512 bytes.
#
# DEVICE LOCATION (QEMU sd.c command trace, r9_base.trace):
#   CMD23(8)+CMD18: 8 sectors at USER LBA 0 (loader scan),
#   CMD17: 1 sector at USER LBA 0 (probe_post read).
#   => the table lives at USER-area byte offset 0x000000 (inside the 64KiB
#   EXBL/header area that partinf.conf leaves before nflasha1), NOT 0x400000.
#   Round 8's "0x400000" was an artifact: QEMU sd.c prints the address AFTER
#   adding the eMMC boot-partition prefix (boot_size=2MiB*2 patched in bionz.c).
#
# IMAGE LAYOUT for QEMU: file = [boot0 2MiB][boot1 2MiB][USER...].
# QEMU maps USER byte X -> file offset X + 0x400000.
#
# usage: mk_nflasha_ptable_r9.py <partinf.conf> <in_user.img> <out_booted.img>
import struct, sys

def parse(p):
    ents = []
    for line in open(p, "rb"):
        line = line.decode("latin1").strip()
        if line.startswith("0x"):
            ents.append(tuple(int(x, 16) for x in line.split(",")))
    return ents

def main():
    conf, src, dst = sys.argv[1:4]
    ents = parse(conf)
    assert len(ents) == 30, "expect 30 partinf entries (part_max=30)"
    tbl = bytearray(512)
    struct.pack_into("<4s4sI", tbl, 0, b"8246", b"1.00", len(ents))
    for i, e in enumerate(ents):
        struct.pack_into("<IIII", tbl, 0x20 + 16 * i, *e)
    import os
    out = open(dst, "wb")
    out.truncate(0)
    out.write(b"\0" * 0x400000)        # boot0 + boot1 (2 MiB each)
    with open(src, "rb") as f:        # USER area (Round 7 a7c_emmc.img layout)
        while True:
            c = f.read(8 << 20)
            if not c:
                break
            out.write(c)
    out.seek(0x400000)                # USER LBA 0 = first sector of user area
    out.write(bytes(tbl))
    out.close()
    print("wrote %d entries (hdr '8246'/'1.00') at file 0x400000 (USER LBA 0) -> %s"
          % (len(ents), dst))

if __name__ == "__main__":
    main()
