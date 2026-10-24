#!/usr/bin/env python3
import struct, os, shutil, subprocess
base = "/home/wubin/qemu-a7c"
tree = base + "/r12/tree"
d12 = tree + "/r12"
os.makedirs(d12, exist_ok=True)
pri = open(base + "/r10/aa2x/Backup.bin", "rb").read()
sec = open(base + "/r10/aa2x/Backup.bak", "rb").read()
print("sizes", hex(len(pri)), hex(len(sec)))
print("hdr pri:", pri[:0x40].hex())
print("hdr sec:", sec[:0x40].hex())
variants = {
    "ctrl": None,
    "e1": 0x00000004,       # DDR0 bottom
    "e2": 0x80001000,       # DDR1 range
    "e3": 0x3fffffe0,       # DDR0 top edge (passes only if pa_uc[0]==DDR0_END default)
}
for name, val in variants.items():
    for tag, src in (("bin", pri), ("bak", sec)):
        b = bytearray(src)
        if val is not None:
            b[0:4] = struct.pack("<I", val)
        open(d12 + "/%s.%s" % (name, tag), "wb").write(bytes(b))
# patch insmod.sh
p = tree + "/usr/bin/insmod.sh"
s = open(p).read()
old = "        insmod $MODPATH/backup.ko Backup_save=0 || { RET=1 ; FAILED_MODULES=\"$FAILED_MODULES,backup\" ; }"
assert old in s, "insmod block not found"
new = """        echo "R12-PROBE-BEGIN"
        for V in ctrl e1 e2 e3 ; do
          insmod $MODPATH/backup.ko Backup_save=0 Backup_pri_file=/r12/$V.bin Backup_sec_file=/r12/$V.bak
          echo "R12-INS-$V-RC=$?"
          if grep -q "Backup_read" /proc/kallsyms ; then echo "R12-BAK-LOADED-WITH-$V" ; break ; fi
        done
        echo "R12-PROBE-END\""""
s = s.replace(old, new)
old2 = "if [ $RET -eq 1 ] ; then"
assert old2 in s
new2 = """echo "R12-MCMN-BEGIN"
if grep -q "Backup_read" /proc/kallsyms ; then
  insmod $MODPATH/mcmn_drv.ko ; echo "R12-MCMN-INS-RC=$?"
  insmod $MODPATH/mmc_drv.ko ; echo "R12-MMCD-INS-RC=$?"
fi
grep -a "Backup_" /proc/kallsyms | head -20
grep -a "^mcmn\\|^backup\\|^mmc_drv" /proc/modules
MAJ=$(grep -a " mcmn" /proc/devices | cut -d" " -f1)
echo "R12-MCMN-MAJOR=$MAJ"
if [ -n "$MAJ" ] ; then rm -f /tmp/mcmn; mknod /tmp/mcmn c $MAJ 0 && /r12/t_mcmn /tmp/mcmn ; fi
echo "R12-MCMN-END"
if [ $RET -eq 1 ] ; then"""
s = s.replace(old2, new2)
open(p, "w").write(s)
print("insmod.sh patched")
