#!/bin/bash
# Round10 usage: ./run_r10.sh <tag> <initrd> [wait]   (image = pt4, cmdline = kemco_a1_c1)
cd ~/qemu-a7c
TAG=$1; INITRD=$2; WAIT=${3:-100}
rm -f r10_$TAG.ser
env A7C_MAP=g A7C_TEXT_OFFSET=0x108000 A7C_CMDLINE_OFFSET=0x103000 A7C_CMDLINE_FILE=parts/kemco_a1_c1.txt \
  timeout $((WAIT+120)) \
  ./qemu-sony/arm-softmmu/qemu-system-arm -M cxd90045 -display none \
  -serial file:r10_$TAG.ser -monitor none \
  -kernel ksrc-v3/arch/arm/boot/vmlinux.bin -initrd $INITRD \
  -drive if=mtd,file=a7c_emmc_pt4.img,format=raw > /dev/null 2>&1
