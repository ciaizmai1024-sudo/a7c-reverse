#!/bin/bash
# Round2 analysis: strings-forensics on fwdump/*, poor-man's backtrace, disasm of spin site.
cd ~/qemu-a7c
A=fwdump/analysis; mkdir -p $A
D=fwdump

# 1) strings with guest-absolute addresses (base added back)
for f in kern:0x60000000 lo:0x00000000 ddra:0x01000000 sram2:0x20000000 stack:0x60439880 lrarea:0x60363fe8; do
  name=${f%%:*}; [ "$name" = "$f" ] && base=0 || base=$(printf 0x%x $((16#${f##*:})))
  python3 - "$D/$name.bin" $((base)) $A/strings_$name.txt <<'EOF'
import sys, subprocess
fn, base, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
r = subprocess.run(["strings","-a","-t","x",fn],capture_output=True,text=True)
with open(out,"w") as f:
    for line in r.stdout.splitlines():
        try:
            off,txt=line.split(None,1)
        except ValueError: continue
        f.write("0x%08X %s\n" % (base+int(off,16), txt))
EOF
done
cat $A/strings_*.txt > $A/strings_all.txt

grep -Ei "linux version|Memory:|ttyAM|Kernel panic|VFS|Unable to mount root|Call trace|Unable to handle kernel|UdtrMain|kemco|init" $A/strings_all.txt > $A/hits.txt || true

# sort by address, keep only lines from kernel text/rodata area, show last readable chunks
sort $A/strings_all.txt -o $A/strings_sorted.txt
grep -E "^0x60[0-9A-Fa-f]{6} " $A/strings_sorted.txt > $A/strings_kern.txt || true
tail -120 $A/strings_kern.txt > $A/last_kern_strings.txt

# longest run of consecutive-ish printable strings in kern dump region
python3 - $A/strings_kern.txt <<'EOF'
import sys,re
lines=[l.rstrip("\n") for l in open(sys.argv[1])]
# print last 60 lines (address order already)
print("\n".join(lines[-60:]))
EOF

# 2) poor-man's backtrace from stack dump (sp-0x100, 4KB)
python3 - $D/stack.bin 0x60439880 <<'EOF'
import struct,sys
data=open(sys.argv[1],"rb").read(); base=int(sys.argv[2])
addrs=[]
for i in range(0,len(data)-3,4):
    w=struct.unpack_from("<I",data,i)[0]
    if 0x60000000<=w<0x61200000:
        addrs.append((base+i,w))
for a,w in addrs:
    print("stack 0x%08X -> 0x%08X" % (a,w))
EOF

# 3) disassemble spin site (guest 0x60364000..0x60364500) from kern.bin
python3 - $D/kern.bin <<'EOF'
import sys
data=open(sys.argv[1],"rb").read()
lo,hi=0x60364000,0x60364500
open("/tmp/spin.bin","wb").write(data[lo-0x60000000:hi-0x60000000])
EOF
arm-linux-gnueabi-objdump -D -b binary -m arm --adjust-vma=0x60364000 /tmp/spin.bin > $A/spin_disasm.txt

echo ==== FORENSICS SUMMARY ====
grep -E "SP=0x|pmemsave" fwdump/forensics.log
echo ==== LAST 80 KERNEL-AREA STRINGS ====
tail -80 $A/last_kern_strings.txt
echo ==== HITS SAMPLE ====
wc -l $A/hits.txt; grep -Ei "linux version|Memory:|Kernel panic|VFS|Unable to mount|Call trace|Unable to handle|UdtrMain|kemco" $A/hits.txt | head -40
