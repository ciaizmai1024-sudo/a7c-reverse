#!/bin/bash
# A7C updater boot-chain smoke test on cxd90045 (QEMU 5.1, ma1co/qemu + our patches)
# usage: ./run_qemu_a7c.sh [extra qemu args...]   e.g.: ./run_qemu_a7c.sh -d unimp -D unimp2.log
cd ~/qemu-a7c
LOG=run_a.log
EXTRA=("$@")
for a in "$@"; do :; done
# -append: kemco.txt middle lines joined (machine code prepends "kemco " and appends " *")
CMD=$(sed -n '/^kemco$/!p' parts/kemco.txt | sed '/^\*$/d' | tr '\n' ' ' | tr -s ' ')
echo "CMDLINE: $CMD" > $LOG.start
timeout 150 ./qemu-sony/arm-softmmu/qemu-system-arm -M cxd90045 -display none \
  -serial file:$LOG -monitor none \
  -kernel parts/vmlinux.bin -initrd parts/initrd.img \
  -append "$CMD" \
  -drive if=mtd,file=a7c_emmc.img,format=raw \
  "${EXTRA[@]}" >> $LOG.start 2>&1
echo "QEMU_RC=$?" >> $LOG.start
