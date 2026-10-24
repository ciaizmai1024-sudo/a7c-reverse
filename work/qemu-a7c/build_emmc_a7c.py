#!/usr/bin/env python3
"""Build A7C eMMC raw image (sparse) at the *device-exact* layout.

Layout source: firmware.tar_unpacked/0300_partconf/partinf.conf
(start-addr, size, type, flag per nflasha partition).
Offsets 0x00000000-0x00010000 = EXBL/boot0 area (not dumped yet) -> zeros.

Partition content sources (see README.md):
  camera dump  = nflashaN.bin      (work/l2-camera, on remote as parts/nflashaN.bin)
  pkg          = nflashaN          (firmware.tar_unpacked/0700_part_image/dev)
  zero         = hole in sparse file
round2 changes:
  * a7 now uses the REAL camera dump work/l1-camera/nflasha7.bin (8,388,608 B,
    full partition size; its first 4,992,000 B are byte-identical to the pkg copy,
    rest of the slot is padding zeros). NOTE: ext2 superblock magic sits at
    partition offset 0x438 = standard ext2 at partition offset 0 -> raw partitions
    have NO extra 0x400 header (task sheet note was wrong for a7; verified).
  * a11/a12/a17/a18 get freshly mkfs'd vfat (label 'M', mkdosfs default geometry,
    matching the real small vfat dumps a2/a6/a10/a13 which are mkdosfs FAT12);
    mount.conf's ClusterSize 16384 is what the *kernel mount driver* uses, the
    on-disk format on the camera is mkdosfs-default, so we mimic the device.
  * a16 (/android/system raw): no pkg or camera copy exists -> stays zeros.
"""
import os, re, sys, subprocess

BASE = os.path.expanduser("~/qemu-a7c")
PARTS = os.path.join(BASE, "parts")
OUT = os.path.join(BASE, "a7c_emmc.img")
PARTINF_RE = re.compile(r"^(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)\s*$")

# parse partinf.conf -> {name: (start, size)}
parts = {}
order = []
last_name = None
with open(os.path.join(PARTS, "partinf.conf"), errors="replace") as f:
    for line in f:
        line = line.strip()
        cm = re.search(r"/dev/(nflasha\d+)\b", line)
        if cm:
            last_name = cm.group(1)
        m = PARTINF_RE.match(line)
        if m:
            start, size = int(m.group(1), 16), int(m.group(2), 16)
            name = last_name or ("p%d" % len(parts))
            if name not in parts:  # size-0 dup lines won't override
                if parts.get(name, (None, 0))[1] or name not in parts:
                    parts[name] = (start, size)
                    order.append(name)

# partitions that must be valid vfat on the device (mount.conf type=vfat and we
# have no camera dump): build mkfs images at exact slot size
VFAT_NEEDS = {"nflasha11": 524288000, "nflasha12": 41943040,
              "nflasha18": 20971520, "nflasha17": 104857600}
vfat_img = {}
for n, size in VFAT_NEEDS.items():
    img = os.path.join(PARTS, "vfat_%s.img" % n)
    with open(img, "wb") as f:
        f.truncate(size)
    # mimic device geometry: mkdosfs defaults (auto FAT), label 'M' like a2/a6/a10/a13
    cmd = ["/usr/sbin/mkfs.vfat", "-n", "M", img]
    subprocess.run(cmd, check=True)
    actual = os.path.getsize(img)
    print("mkfs %s: slot %d, fs %d, %s" % (n, size, actual, " ".join(cmd)))
    vfat_img[n] = img

# content source per partition: 'camera' .bin, pkg raw name, vfat image, or zero
SRC = {}
for n in parts:
    idx = re.match(r"nflasha(\d+)$", n)
    if not idx:
        continue
    k = idx.group(1)
    cam = os.path.join(PARTS, "nflasha%s.bin" % k)
    pkg = os.path.join(PARTS, "nflasha%s" % k)
    if n in vfat_img:
        SRC[n] = vfat_img[n]
    elif os.path.exists(cam):
        SRC[n] = cam
    elif os.path.exists(pkg):
        SRC[n] = pkg

# "updater minimal set" plus everything else zero-filled: a11 stays zeros
total = max(s + sz for (s, sz) in parts.values() if sz > 0)
print("image size = 0x%X (%d bytes)" % (total, total))

with open(OUT, "wb") as out:
    out.truncate(total)  # sparse
    # 0x0000-0x00010000: EXBL/boot0 zeros (already zero via truncate hole; write explicit zeros)
    out.seek(0)
    out.write(b"\0" * 0x10000)
    for n in order:
        start, size = parts[n]
        if size == 0:
            continue
        if n not in SRC:
            print("%-10s 0x%08X (%9d)  <zeros>" % (n, start, size))
            continue
        src = SRC[n]
        sz = os.path.getsize(src)
        if sz > size:
            sys.exit("FATAL: %s (%d) bigger than slot %d" % (src, sz, size))
        with open(src, "rb") as f:
            out.seek(start)
            got = 0
            while True:
                buf = f.read(1 << 20)
                if not buf:
                    break
                out.write(buf)
                got += len(buf)
        print("%-10s 0x%08X (%9d)  <- %s (%d)" % (n, start, size, os.path.basename(src), got))
print("wrote", OUT)
