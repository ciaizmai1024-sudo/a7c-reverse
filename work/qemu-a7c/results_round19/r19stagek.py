import subprocess, os
os.chdir(os.path.expanduser("~/qemu-a7c"))
S = "echo zzz888ZZZ | sudo -S "
def sh(c, inp=None):
    r = subprocess.run(c, shell=True, capture_output=True, input=inp, text=False)
    if r.returncode: print("FAIL", c, r.stderr.decode()[:300])
    return r

# key bytes KEY_90045
K = bytes([0xc1,0xaa,0x8f,0x7c,0x46,0x34,0x1f,0xfe,0xd1,0x55,0x89,0xfc,0x81,0x70,0xa6,0xbb,
           0x59,0x25,0xe8,0x5f,0x62,0x82,0xd7,0xf9,0x5b,0xa3,0xfd,0xf5,0xd3,0x03,0xe0,0x6b])
octal = "".join("\\%03o" % b for b in K)
block = (
 'echo R19K-BEFORE\n'
 'dd if=/dev/mem of=/ramdsk/mnt/r19key_pre.bin bs=4096 skip=996367 count=1 2>/dev/null; echo "R19K-PRE-RC=$?"\n'
 f'printf \'{octal}\' > /r19k.bin; ls -l /r19k.bin | sed "s/^/R19K-SIZE /"\n'
 'dd of=/dev/mem if=/r19k.bin bs=1 seek=4065591296 count=32 conv=notrunc 2>/dev/null; echo "R19K-WRITE-RC=$?"\n'
 'dd if=/dev/mem of=/ramdsk/mnt/r19key_post.bin bs=4 count=8 skip=1016397760 2>/dev/null; echo "R19K-POST-RC=$?"\n'
 'dd if=/dev/mem of=/ramdsk/mnt/r19skd1k.bin bs=1024 count=1 skip=65533 2>/dev/null; echo "R19K-SKD1K-RC=$?"\n'
 'sync\n')
# offsets: 0xF340F000/4096=996367(page read); /4=1016397760; byte seek 0xF340F000=4065591296? check:
assert 0xF340F000 // 4096 == 0xF340F, hex(0xF340F)
# fix: 0xF340F000/4 = 0x3CD43C00 = 1020175360 ; seek bytes = 0xF340F000 = 4064313344? compute properly
A = 0xF340F000; B = 0xFFFF5000
block = block.replace('skip=996367 count=1', 'skip=%d count=1' % (A // 4096))
block = block.replace('seek=4065591296', 'seek=%d' % A)
block = block.replace('count=8 skip=1016397760', 'count=8 skip=%d' % (A // 4))
block = block.replace('skip=65533', 'skip=%d' % (B // 1024))
print("insert block offsets ok:", A//4096, A, A//4, B//1024)

pass  # tree_k precreated
# rebuild shim without FIXKEY
sh("cd r19src && arm-linux-gnueabi-gcc -marm -nostdlib -static -shared -fPIC -O2 -fno-builtin -DFORCE0 -o r19fshim_r19k.so r19fshim_full.c")
sh("cp r19src/r19fshim_r19k.so r19src/tree_k/r14bin/r17fshim_r17pass.so")
p = "r19src/tree_k/usr/bin/execute_ufp.sh"
s = open(p).read()
anchor = '\tmount -t vfat /dev/mmca1 /ramdsk/mnt 2>/dev/null; echo "R14B-MOUNT-RC=$?"\n'
assert anchor in s
open(p, "w").write(s.replace(anchor, anchor + block, 1))
sh("sudo mkfs.cramfs -b 4096 r19src/tree_k results_round19/initrd_r19kbt.img", inp=b"zzz888ZZZ\n")
sh("cp a7c_emmc_r19bt.img a7c_emmc_r19kbt.img")
print(subprocess.run("md5sum results_round19/initrd_r19kbt.img a7c_emmc_r19kbt.img r19src/r19fshim_r19k.so", shell=True, capture_output=True, text=True).stdout)
sh('nohup ./results_round19/run_r19.sh kbt a7c_emmc_r19kbt.img results_round19/initrd_r19kbt.img 1200 > r19_runK.log 2>&1 &')
print("launched kbt")
