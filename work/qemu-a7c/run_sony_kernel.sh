#!/bin/bash
# Round3 skeleton: boot the Sony GPL kernel (fetched/built by the sony-src agent)
# on our cxd90045 machine with the A7C eMMC image. Kernel path is a placeholder.
# Usage: SONY_KERNEL=~/sony-src/.../zImage ./run_sony_kernel.sh
# NOTES:
#  - Our QEMU loads -kernel at PA TEXT_OFFSET=0x00108000; Sony A7C zImage links at
#    VA/PA base 0x60000000 with PAGE_OFFSET=0x60000000 (nl patch) - the 2GB DDR0 map
#    covers both pre-MMU (PA 0x60000000) and post-MMU (PA 0x00xxxxxx) phases.
#  - Round2 showed the *updater* kernel dies in kmem_cache_init (start_kernel+0x16c)
#    with a first-level translation fault; if the GPL kernel has the same nl mem layout
#    (mem=1G@0 + mem=1016M@0x80000000@1 + memrsv=0x20000000@0x20000000:uc), consider
#    giving QEMU *mirrors* instead of a flat 2GB: DDR0 1GB @0 + alias window
#    0x40000000..0x80000000 -> first 1GB (memory_region_init_alias), + DDR1 @0x80000000.
#  - klog: log_buf text was found at PA 0x0047xxxx (VA 0x6047xxxx) in round2; use
#    qmp_forensics.py + pmemsave 0x0 0x1000000 (lo.bin) then strings -a -t x lo.bin.
cd ~/qemu-a7c
KER=${SONY_KERNEL:-PUT_SONY_ZIMAGE_PATH_HERE}   # TODO: point to sony-src zImage once present
CMD="root=/dev/nflasha7 rw noatime noalign init=/init console=ttyAM0,115200n8 xrstreq=0 wdt.mode=0 stack_usage=y cxd90014.bam=Y cfg.uart=15 wdt.timeout=500 softlockup_panic=0 mem=1G@0 memrsv=1M@0 memrsv=0x75e000@0x02E68000 memrsv=0x500000@0x09b00000 memrsv=0x20000000@0x20000000:uc mem=1016M@0x80000000@1"
timeout 300 ./qemu-sony/arm-softmmu/qemu-system-arm -M cxd90045 -display none \
  -serial file:sony_run.log -monitor none -qmp unix:mon.sock,server,nowait \
  -kernel "$KER" -append "$CMD" \
  -drive if=mtd,file=a7c_emmc.img,format=raw "$@" &
QPID=$!
# after 120s, dump PA 0..16MB (covers kernel .text/.data/log_buf at PA ~0x100000-0x500000)
( sleep 120; python3 qmp_forensics.py "$PWD/mon.sock" "$PWD/fwdump_sony" 1 ) &
wait $QPID; tail -5 sony_run.log
