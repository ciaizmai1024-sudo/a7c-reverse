#!/bin/bash
# T4 experiments: (a) kemco cmdline + maxcpus=0 ; (c) full-root cmdline, NO initrd.
# Each: 75s of boot, then forensics dumps log memory, then next.
cd ~/qemu-a7c
K=$(sed -n '/^kemco$/!p' parts/kemco.txt | sed '/^\*$/d' | tr '\n' ' ' | tr -s ' ')
run_one() { # $1=tag  $2=cmdline  $3.. extra qemu args
  local tag=$1; local cmd=$2; shift 2
  rm -f fwdump_$tag; mkdir -p fwdump_$tag
  ./run_round2.sh 75 -append="$cmd" "$@" > round2_$tag.log 2>&1
  mv fwdump/* fwdump_$tag/ 2>/dev/null
  # quick harvest: strings of lo.bin around kernel data
  for f in lo kern; do
    python3 - "$fwdump_$tag/$f.bin" $([ $f = lo ] && echo 0 || echo 0x60000000) "$fwdump_$tag/s_$f.txt" <<'EOF'
import sys,subprocess
fn,base,out=sys.argv[1],int(sys.argv[2],0),sys.argv[3]
r=subprocess.run(["strings","-a","-t","x",fn],capture_output=True,text=True)
with open(out,"w") as f:
    for line in r.stdout.splitlines():
        p=line.split(None,1)
        if len(p)==2: f.write("0x%08X %s\n"%(base+int(p[0],16),p[1]))
EOF
  done
  cat fwdump_$tag/s_lo.txt fwdump_$tag/s_kern.txt | sort > fwdump_$tag/s_all.txt
  echo "== $tag: oops=$(grep -c 'Internal error' fwdump_$tag/s_all.txt) panics=$(grep -c 'Kernel panic' fwdump_$tag/s_all.txt) vfs=$(grep -ci 'VFS\|ram0\|nflasha\|Freeing init' fwdump_$tag/s_all.txt)"
  tail -6 fwdump_$tag/forensics.log | grep -E "R1[345]=|SP="
  grep -E "VFS|Unable to mount|RAMDISK|init|Run /init|Freeing" fwdump_$tag/s_all.txt | tail -15
}
run_one maxcpus0 "$K maxcpus=0"
run_one fullroot "root=/dev/nflasha7 rw noatime noalign init=/init console=ttyAM0,115200n8 xrstreq=0 wdt.mode=0 stack_usage=y cxd90014.bam=Y cfg.uart=15 wdt.timeout=500 softlockup_panic=0 tmonitor.addr=0x1A00000 tmonitor.size=0x500000 tmonitor.mask=0 mem=1G@0 memrsv=1M@0 memrsv=0x75e000@0x02E68000 memrsv=0x500000@0x09b00000 memrsv=0x20000000@0x20000000:uc mem=1016M@0x80000000@1" NOINITRD
