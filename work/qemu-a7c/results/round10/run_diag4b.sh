#!/bin/sh
insmod /usr/kmod/devno.ko
insmod /usr/kmod/dmac.ko
insmod /usr/kmod/ldec.ko
insmod /usr/kmod/emmc.ko tbl=0x80000000
insmod /usr/kmod/osal_utm.ko
insmod /usr/kmod/osal_uipc.ko
insmod /usr/kmod/utimer.ko
insmod /usr/kmod/stream.ko
insmod /usr/kmod/stream2.ko
insmod /usr/kmod/sio.ko
sleep 1
echo ZZDIAG-A
mkdir -p /mnt1
mount -t tmpfs -o size=32M tmpfs /mnt1
mkdir -p /setting
mount -t vfat -o posix_attr,rw,nodiratime,noatime,shortname=mixed,sync /dev/nflasha2 /setting
cat /setting/Backup.bin > /mnt1/a.bin
cat /setting/Backup.bin > /mnt1/a.bak
dd if=/mnt1/a.bin of=/mnt1/m.bin bs=1 count=256 2>/dev/null
dd if=/mnt1/a.bin of=/mnt1/m.bin bs=1 skip=256 seek=256 2>/dev/null
printf "Back" | dd of=/mnt1/m.bin bs=1 seek=12 conv=notrunc 2>/dev/null
cmp /mnt1/a.bin /mnt1/m.bin; echo cmprc=$?
insmod /usr/kmod/backup.ko Backup_save=0 Backup_pri_file=/mnt1/m.bin Backup_sec_file=/mnt1/m.bin
echo "bkrcM=$?"
echo ZZDIAG-B
sleep 30
