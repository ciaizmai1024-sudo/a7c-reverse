base="/home/wubin/qemu-a7c"
p=base+"/r14/tree/usr/bin/insmod.sh"; s=open(p).read()
old='mount -t vfat /dev/mmca1 /ramdsk/mnt; echo "R14-TESTMOUNT-RC=$?"\nls -la /ramdsk/mnt | sed "s/^/R14-LS /"\numount /ramdsk/mnt\n'
assert old in s, "cardsetup block"
new='mount -t vfat /dev/mmca1 /ramdsk/mnt; echo "R14-TESTMOUNT-RC=$?"\nls -la /ramdsk/mnt | sed "s/^/R14-LS /"\necho "R14-CARD-MOUNT-KEPT"\n'
s=s.replace(old,new); open(p,"w").write(s)
p2=base+"/r14/tree/usr/bin/execute_ufp.sh"; t=open(p2).read()
o2='\tinsmodMediaDriver\n\tsdfileinput.elf || {'
assert o2 in t, "mode5 branch"
n2=('\tinsmodMediaDriver\n'
    '\tmount -t vfat /dev/mmca1 /ramdsk/mnt 2>/dev/null; echo "R14B-MOUNT-RC=$?"\n'
    '\tls -la /ramdsk/mnt | sed "s/^/R14B-LS /"\n'
    '\texport LD_PRELOAD="/usr/lib/libSysDef.so /r14bin/r14fshim_r14b.so"\n'
    '\techo "R14B-PRELOAD=$LD_PRELOAD"\n'
    '\tsdfileinput.elf || {')
t=t.replace(o2,n2); open(p2,"w").write(t)
print("patched insmod.sh + execute_ufp.sh")
