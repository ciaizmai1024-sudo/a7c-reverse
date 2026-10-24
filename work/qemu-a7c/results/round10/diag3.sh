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
mkdir -p /setting
mount -t vfat -o posix_attr,rw,nodiratime,noatime,shortname=mixed,sync /dev/nflasha2 /setting
echo "mountrc=$?"
insmod /usr/kmod/backup.ko Backup_save=0 Backup_debug=1
echo "bkrcD=$?"
echo ZZDIAG-B
sleep 25
mkdir -p /mnt1
mount -t tmpfs -o size=16M tmpfs /mnt1
cat /setting/Backup.bin > /mnt1/Backup.bin
cat /setting/Backup.bin > /mnt1/Backup.bak
insmod /usr/kmod/backup.ko Backup_save=0 Backup_debug=1 Backup_pri_file=/mnt1/Backup.bin Backup_sec_file=/mnt1/Backup.bak
echo "bkrcE=$?"
echo ZZDIAG-C
sleep 25
