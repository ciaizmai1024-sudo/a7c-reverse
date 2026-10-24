#!/usr/bin/env python3
base = "/home/wubin/qemu-a7c"
# patch init: time-box us_darwin_init.sh
p = base + "/r12/tree/sbin/init"
s = open(p).read()
old = "\tus_darwin_init.sh\n"
assert old in s, "init darwin line"
new = "\tR12-DARWIN-INIT-BEGIN\n\tus_darwin_init.sh & Dpid=$!\n\tsleep 20\n\tkill -9 $Dpid 2>/dev/null\n\techo R12-DARWIN-INIT-KILLED\n"
s = s.replace(old, new)
open(p, "w").write(s)
# patch insmod.sh mcmn block: mknod under /ramdsk, log mmc symbol
p2 = base + "/r12/tree/usr/bin/insmod.sh"
s2 = open(p2).read()
old2 = '''if [ -n "$MAJ" ] ; then rm -f /tmp/mcmn; mknod /tmp/mcmn c $MAJ 0 && /r12/t_mcmn /tmp/mcmn ; fi'''
assert old2 in s2, "mcmn probe"
new2 = '''mkdir -p /ramdsk; if [ -n "$MAJ" ] ; then rm -f /ramdsk/mcmn; mknod /ramdsk/mcmn c $MAJ 0 && /r12/t_mcmn /ramdsk/mcmn ; fi'''
s2 = s2.replace(old2, new2)
open(p2, "w").write(s2)
print("r12d patches ok")
