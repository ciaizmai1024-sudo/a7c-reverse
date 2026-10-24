#!/usr/bin/env python3
"""Round5 forensics: periodic snaps (ring + pgtbl/blob + bootrom window),
final regs x2, mtree dump, targeted pmemsave. Based on qmp_forensics.py."""
import socket, json, sys, time, os, re
sock_path, ddir, wait = sys.argv[1], sys.argv[2], int(sys.argv[3])
snap_every = int(sys.argv[4]) if len(sys.argv) > 4 else 10
snap_specs = sys.argv[5] if len(sys.argv) > 5 else "0x400000:0x200000"
SNAPS = [(int(a.split(":")[0],16), int(a.split(":")[1],16)) for a in snap_specs.split(",")]
os.makedirs(ddir, exist_ok=True)
def connect():
    for _ in range(120):
        try:
            s = socket.socket(socket.AF_UNIX); s.connect(sock_path); return s
        except OSError: time.sleep(1)
    raise SystemExit("no qmp socket")
s = connect(); f = s.makefile("rw")
def send(o): f.write(json.dumps(o)+"\r\n"); f.flush()
def read():
    l = f.readline(); return json.loads(l) if l else None
read(); send({"execute":"qmp_capabilities"}); read()
def hmp(cmd):
    send({"execute":"human-monitor-command","arguments":{"command-line":cmd}})
    while True:
        r = read()
        if r is None: return ""
        if "return" in r: return r["return"] or ""
log = open(os.path.join(ddir,"forensics.log"),"w")
def P(*a): print(*a,flush=True); print(*a,file=log); log.flush()
t0=time.time(); snap_files=[]
while time.time()-t0 < wait:
    time.sleep(min(snap_every, wait-(time.time()-t0)))
    el=int(time.time()-t0)
    for (addr,size) in SNAPS:
        out="%s/snap_%04d_%x.bin"%(ddir,el,addr)
        r=hmp("pmemsave 0x%X 0x%X %s"%(addr,size,out))
        if "error" in r.lower(): P("snap t=%d 0x%X ERR %r"%(el,addr,r[:120]))
        else: snap_files.append((el,addr,out))
    P("snapshots t=%d: %d files"%(el,len(snap_files)))
P("=== info registers (full) ==="); P(hmp("info registers"))
for addr,size,out in [
        (0xffff0000,0x2000,"vectors_pa.bin"),
        (0x00132000,0x8000,"pgtbl.bin"),
        (0x03480000,0x40000,"boottime_klog.bin"),
        (0x20020000,0x4000,"sram_mailbox.bin")]:
    r=hmp("pmemsave 0x%X 0x%X %s"%(addr,size,out)); P("final %s 0x%X -> %r"%(out,addr,r[:100]))
for cmd,fn in [("info mtree -f","mtree_f.txt"),("info mtree","mtree.txt")]:
    out=hmp(cmd)
    open(os.path.join(ddir,fn),"w").write(out)
    P("wrote %s (%d bytes, rc-head %r)"%(fn,len(out),out[:80]))
P("=== 2nd regs sample (+10s) ==="); time.sleep(10); P(hmp("info registers"))
hmp("quit"); print("qemu quit",flush=True); log.close()
PRINTABLE=set(range(0x20,0x7f))|{9}
def lines_of(fn):
    data=open(fn,"rb").read(); pos=0; cur=bytearray(); raw=[]
    for b in data:
        if b==0x0a or b>0x7f or (b<0x20 and b!=9):
            if len(cur)>=5: raw.append(cur.decode("latin1").rstrip())
            cur=bytearray()
        else: cur.append(b)
    if len(cur)>=5: raw.append(cur.decode("latin1").rstrip())
    return [l for l in raw if sum(c in PRINTABLE for c in l)>=len(l)*0.9]
TS=re.compile(r"^\[\s*(\d+\.\d+)\]")
def wrap_rotate(lines):
    tss=[]; last=None
    for l in lines:
        m=TS.match(l)
        if m: last=float(m.group(1))
        tss.append(last)
    worst,wi=0.0,None
    for i in range(1,len(tss)):
        if tss[i] is not None and tss[i-1] is not None:
            d=tss[i-1]-tss[i]
            if d>worst: worst,wi=d,i
    if wi is not None and worst>1.0: return lines[wi:]+lines[:wi]
    return lines
def merge(G,S):
    maxk=min(len(G),len(S),4000)
    for k in range(maxk,0,-1):
        if G[-k:]==S[:k]: return G+S[k:]
    for k in range(maxk,0,-1):
        g,s_=G[-k:],S[:k]
        if sum(1 for a,b in zip(g,s_) if a!=b)<=3: return G+S[k:]
    return G+["--(no overlap)--"]+S
ring=[x for x in snap_files if x[1]==0x400000]
G=[]
for (el,addr,fn) in sorted(ring):
    ls=wrap_rotate(lines_of(fn))
    G=ls if not G else merge(G,ls)
out=os.path.join(ddir,"logbuf_raw.txt")
open(out,"w").write("\n".join(G)+"\n")
P("wrote %s (%d lines)"%(out,len(G)))
KEY=re.compile(r"(Linux version|Booting Linux|Machine|Memory|CPU|slab|SLUB|BUG|Oops|Unable to handle|Internal error|kernel BUG|init|VFS|Freeing|Run /init|Mounted|ramdisk|initrd|nflash|Udtr|kernel panic|try to access|Accesses|pgd|workqueue|Kernel command line|Normal zone|high_memory|nodeorder|l2x0|Addmem|Memory:|Lithic|nl)",re.I)
keep,inblk=[],False
for l in G:
    if TS.match(l) or l.startswith("<") or l.startswith("[<") or l.startswith("Exception stack") or l.startswith("Code:"):
        inblk=KEY.search(l) is not None or inblk; keep.append(l)
    elif inblk and (l.strip()=="" or l.startswith("r") or l.startswith("pc :") or l.startswith("lr :") or l.startswith("sp :") or l.startswith("ips :") or l.startswith("psr :")):
        keep.append(l)
    elif l.startswith("2.6.") or l.startswith("3.0.") or l.startswith("CPU: "):
        keep.append(l)
open(os.path.join(ddir,"logbuf.txt"),"w").write("\n".join(keep)+"\n")
