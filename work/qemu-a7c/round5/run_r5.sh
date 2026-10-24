#!/bin/bash
# Round5: M4 base + kemco variants; optional -d logging.
# usage: ./run_r5.sh <tag> <wait> <INT|M4|M6|M7|M8a|M8b|M9> [DLOG]
cd ~/qemu-a7c
TAG=$1; WAIT=${2:-60}; MODE=${3:-M4}; DLOG=${4:-}
KERNEL=ksrc/arch/arm/boot/vmlinux.bin
INITRD="-initrd parts/initrd.img"
case "$MODE" in
  INT|M4) CF=parts/kemco_m4.txt;;
  M6) CF=parts/kemco_m6.txt;;
  M7) CF=parts/kemco_m7.txt;;
  M8a) CF=parts/kemco_m8a.txt;;
  M8b) CF=parts/kemco_m8b.txt;;
  M9) CF=parts/kemco_m9.txt;;
esac
SNAPS="0x00400000:0x200000,0x00132000:0x8000,0xffff0000:0x2000"
rm -rf fwdump5_$TAG mon5.sock run5_$TAG.log run5_$TAG.log.start int5_$TAG.log
DOPT=""
[ -n "$DLOG" ] && DOPT="-d $DLOG -D int5_$TAG.log"
echo "MODE=$MODE CMDLINE_FILE=$CF DOPT=$DOPT" > run5_$TAG.log.start
env A7C_MAP=f A7C_CMDLINE_FILE=$CF timeout $((WAIT+180)) \
 ./qemu-sony/arm-softmmu/qemu-system-arm -M cxd90045 -display none \
  -serial file:run5_$TAG.log -monitor none -qmp unix:mon5.sock,server,nowait $DOPT \
  -kernel $KERNEL $INITRD -drive if=mtd,file=a7c_emmc.img,format=raw >> run5_$TAG.log.start 2>&1 &
python3 qmp_forensics5.py "$PWD/mon5.sock" "fwdump5_$TAG" "$WAIT" ${SNAPEVERY:-15} "$SNAPS" >> run5_$TAG.log.start 2>&1
wait
echo "DONE $TAG rc=$?" >> run5_$TAG.log.start
