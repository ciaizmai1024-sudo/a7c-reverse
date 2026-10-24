#!/bin/bash
# Round3-V: Sony cxd90045_qemu_nfs_defconfig kernel (raw vmlinux.bin @ PA 0x138000).
# usage: ./run_sony.sh <tag> <wait_secs> <V1|V2|V3>
#   V1: no -append -> kernel built-in CONFIG_CMDLINE (nfsroot...), no initrd. Criteria: console alive.
#   V2: a1 kemco cmdline + real initrd @PA 0x700000, with QEMU-defconfig mem/klog overrides merged.
#   V3: like V2 but kernel built from shipped .config + CXD900X0_QEMU=y (TEXT 0x108000, CMDLINE_PHYS 0x103000 via env).
cd ~/qemu-a7c
TAG=$1; WAIT=${2:-90}; MODE=${3:-V1}
KERNEL=ksrc/arch/arm/boot/vmlinux.bin
KEMCO=$(sed -n '/^kemco$/!p' parts/kemco.txt | sed '/^\*$/d' | tr '\n' ' ' | tr -s ' ')
INITRD=""; CMD=""; ENVV=""
SNAPS="0x02120000:0x20000,0x00400000:0x200000"
case "$MODE" in
  V1) ;;
  V2) CMD="$KEMCO amba2.console=1 cfg.uart=0xf klog.addr=0x02120000 klog.size=0x20000"
      INITRD="-initrd parts/initrd.img"; ENVV="A7C_MAP=a";  # a: ddr0 1G + ddr1 1016M(匹配 kemco bank) + 0x60000000 镜像窗
      SNAPS="0x02120000:0x20000,0x00400000:0x200000";;
  V3) ENVV="A7C_TEXT_OFFSET=0x108000 A7C_CMDLINE_OFFSET=0x103000"
      KERNEL=kb-ship/arch/arm/boot/vmlinux.bin
      CMD="$KEMCO amba2.console=1 cfg.uart=0xf klog.addr=0x034A0000 klog.size=0x20000"
      INITRD="-initrd parts/initrd.img"
      SNAPS="0x034A0000:0x20000,0x00400000:0x200000";;
esac
rm -rf fwdump_$TAG mon3.sock run3_$TAG.log run3_$TAG.log.start
[ -n "$CMD" ] && echo "APPEND: $CMD" > run3_$TAG.log.start
env $ENVV timeout $((WAIT+180)) ./qemu-sony/arm-softmmu/qemu-system-arm -M cxd90045 -display none \
  -serial file:run3_$TAG.log -monitor none -qmp unix:mon3.sock,server,nowait \
  -kernel $KERNEL $INITRD ${CMD:+-append "$CMD"} \
  -drive if=mtd,file=a7c_emmc.img,format=raw >> run3_$TAG.log.start 2>&1 &
python3 qmp_forensics.py "$PWD/mon3.sock" "fwdump_$TAG" "$WAIT" 15 "$SNAPS" >> run3_$TAG.log.start 2>&1
wait
echo "DONE $TAG rc=$?" >> run3_$TAG.log.start
echo "===== $TAG serial:"; cat run3_$TAG.log 2>/dev/null | head -40
