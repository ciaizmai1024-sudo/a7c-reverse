#!/usr/bin/env python3
p = "/home/wubin/qemu-a7c/r12/tree/usr/bin/insmod.sh"
s = open(p).read()
old = '''        echo "R12-PROBE-BEGIN"
        for V in v1 v2 v3 v4 v5 v6 ; do
          insmod $MODPATH/backup.ko Backup_save=0 Backup_pri_file=/r12/$V.bin Backup_sec_file=/r12/$V.bak
          echo "R12-INS-$V-RC=$?"
          if grep -q "Backup_read" /proc/kallsyms ; then echo "R12-BAK-LOADED-WITH-$V" ; break ; fi
        done
        echo "R12-PROBE-END"'''
assert old in s, "block not found"
new = '''        echo "R12-PROBE-BEGIN"
        insmod $MODPATH/backup.ko Backup_load=1 Backup_save=0 Backup_pri_file=/r12/ctrl.bin Backup_sec_file=/r12/ctrl.bak
        echo "R12-INS-R1-LOAD1-REAL-RC=$?"
        grep -c "Backup_" /proc/kallsyms | sed "s/^/R12-KSYMS=/"
        if grep -q "Backup_read" /proc/kallsyms ; then echo "R12-BAK-LOADED-LOAD1-REAL" ; fi
        if ! grep -q "Backup_read" /proc/kallsyms ; then
          insmod $MODPATH/backup.ko Backup_load=1 Backup_save=0 Backup_pri_file=/r12/v2.bin Backup_sec_file=/r12/v2.bak
          echo "R12-INS-R2-LOAD1-MIN-RC=$?"
          if grep -q "Backup_read" /proc/kallsyms ; then echo "R12-BAK-LOADED-LOAD1-MIN" ; fi
        fi
        if ! grep -q "Backup_read" /proc/kallsyms ; then
          insmod $MODPATH/backup.ko Backup_save=0
          echo "R12-INS-R3-DEFAULT-CTRL-RC=$?"
        fi
        echo "R12-PROBE-END"'''
s = s.replace(old, new)
open(p, "w").write(s)
print("patched r12c insmod.sh")
