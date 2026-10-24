#!/bin/bash
# Round3 runner: same "farthest" round2 config (real a1 zImage + initrd + kemco
# cmdline + eMMC), but with A7C_MAP env selecting the memory map compiled into
# bionz.c, and periodic log_buf snapshots via qmp_forensics.py.
# usage: ./run_round3.sh <tag> <wait_secs> <map orig|a|b|c|d> [SNAPS=addr:size,.. via env] [extra/override args like run_round2.sh]
cd ~/qemu-a7c
TAG=$1; WAIT=${2:-120}; MAPV=${3:-orig}
shift 3
SNAPS=${SNAPS:-0x400000:0x100000}
SNAPEVERY=${SNAPEVERY:-10}
INITRD="-initrd parts/initrd.img"
CMD=""
EXTRA=()
for a in "$@"; do
  case "$a" in
    NOINITRD) INITRD="";;
    -append=*) CMD="${a#-append=}";;
    *) EXTRA+=("$a");;
  esac
done
[ -z "$CMD" ] && CMD=$(sed -n '/^kemco$/!p' parts/kemco.txt | sed '/^\*$/d' | tr '\n' ' ' | tr -s ' ')
rm -rf fwdump_$TAG mon3.sock run3_$TAG.log run3_$TAG.log.start
echo "MAP=$MAPV CMDLINE: $CMD INITRD: $INITRD" > run3_$TAG.log.start
A7C_MAP=$MAPV A7C_ATAGMEM=$([ "$MAPV" = c ] && echo 1) \
timeout $((WAIT+180)) ./qemu-sony/arm-softmmu/qemu-system-arm -M cxd90045 -display none \
  -serial file:run3_$TAG.log -monitor none \
  -qmp unix:mon3.sock,server,nowait \
  -kernel parts/vmlinux.bin $INITRD \
  -append "$CMD" \
  -drive if=mtd,file=a7c_emmc.img,format=raw \
  "${EXTRA[@]}" >> run3_$TAG.log.start 2>&1 &
python3 qmp_forensics.py "$PWD/mon3.sock" "fwdump_$TAG" "$WAIT" "$SNAPEVERY" "$SNAPS" \
  >> run3_$TAG.log.start 2>&1
wait
echo "QEMU_RC=$?" >> run3_$TAG.log.start
echo "DONE $TAG" >> run3_$TAG.log.start
tail -4 run3_$TAG.log.start
