#!/bin/bash
# Round7: V3 = factory config-shipped-2.00 + CXD900X0_QEMU=y  (TEXT_OFFSET 0x108000)
# usage: ./run_r7.sh <tag> <map> <cmdlinefile> <wait> [DLOG]
cd ~/qemu-a7c
TAG=$1; MAP=$2; CF=$3; WAIT=${4:-60}; DLOG=${5:-}
KERNEL=ksrc-v3/arch/arm/boot/vmlinux.bin
# V3: log_buf ring PA 0x004e7da0 (len 1<<13), page tables PA 0x00102000, klog/boottime 0x03480000
SNAPS="0x004e0000:0x220000,0x00102000:0x8000,0x03480000:0x60000,0x004c0000:0x40000"
rm -rf fwdump7_$TAG mon7.sock run7_$TAG.log int7_$TAG.log
DOPT=""
[ -n "$DLOG" ] && DOPT="-d $DLOG -D int7_$TAG.log"
echo "MAP=$MAP CMD=$CF WAIT=$WAIT DOPT=$DOPT" > run7_$TAG.log.start
env A7C_MAP=$MAP A7C_TEXT_OFFSET=0x108000 A7C_CMDLINE_OFFSET=0x103000 A7C_CMDLINE_FILE=$CF \
  timeout $((WAIT+180)) \
  ./qemu-sony/arm-softmmu/qemu-system-arm -M cxd90045 -display none \
  -serial file:run7_$TAG.log -monitor none -qmp unix:mon7.sock,server,nowait $DOPT \
  -kernel $KERNEL -initrd parts/initrd.img -drive if=mtd,file=a7c_emmc.img,format=raw >> run7_$TAG.log.start 2>&1 &
python3 qmp_forensics5.py "$PWD/mon7.sock" "fwdump7_$TAG" "$WAIT" ${SNAPEVERY:-2} "$SNAPS" >> run7_$TAG.log.start 2>&1
wait
echo "DONE $TAG rc=$?" >> run7_$TAG.log.start
