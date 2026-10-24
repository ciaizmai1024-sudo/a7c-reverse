#!/bin/bash
# Round2 T2: longest old-config boot (updater vmlinux.bin + initrd + kemco cmdline),
# with QMP socket; forensics script dumps memory at T+WAIT and quits QEMU.
# usage: ./run_round2.sh <wait_secs> <extra qemu args...>
cd ~/qemu-a7c
WAIT=${1:-120}; shift
EXTRA=()
INITRD="-initrd parts/initrd.img"
CMD=""
for a in "$@"; do
  case "$a" in
    NOINITRD) INITRD="";;
    -append=*) CMD="${a#-append=}";;
    *) EXTRA+=("$a");;
  esac
done
[ -z "$CMD" ] && CMD=$(sed -n '/^kemco$/!p' parts/kemco.txt | sed '/^\*$/d' | tr '\n' ' ' | tr -s ' ')
rm -f mon.sock run2.log run2.log.start
echo "CMDLINE: $CMD INITRD: $INITRD" > run2.log.start
timeout 240 ./qemu-sony/arm-softmmu/qemu-system-arm -M cxd90045 -display none \
  -serial file:run2.log -monitor none \
  -qmp unix:mon.sock,server,nowait \
  -kernel parts/vmlinux.bin $INITRD \
  -append "$CMD" \
  -drive if=mtd,file=a7c_emmc.img,format=raw \
  "${EXTRA[@]}" > run2.log.start 2>&1 &
QPID=$!
python3 qmp_forensics.py "$PWD/mon.sock" "$PWD/fwdump" "$WAIT"
wait $QPID
echo "QEMU_RC=$?" >> run2.log.start
tail -3 run2.log.start
