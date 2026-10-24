#!/bin/bash
# Round11: ./run_r11.sh <tag> <initrd> [wait]
cd ~/qemu-a7c
TAG=$1; INITRD=$2; WAIT=${3:-100}
rm -f r12_$TAG.ser
env A7C_MAP=g A7C_TEXT_OFFSET=0x108000 A7C_CMDLINE_OFFSET=0x103000 A7C_CMDLINE_FILE=parts/kemco_a1_c1.txt \
  timeout $((WAIT+120)) \
  ./qemu-sony/arm-softmmu/qemu-system-arm -M cxd90045 -display none \
  -no-reboot -serial file:r12nb_$TAG.ser -monitor none \
  -kernel ksrc-v3/arch/arm/boot/vmlinux.bin -initrd $INITRD \
  -drive if=mtd,file=${IMG:-a7c_emmc_pt4.img},format=raw > /dev/null 2>&1
