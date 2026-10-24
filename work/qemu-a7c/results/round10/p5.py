import re,hashlib,os
vals=[];cur=None
for ln in open("parts/partinf.conf",errors="ignore"):
    if isinstance(ln,bytes): ln=ln.decode("utf8","ignore")
    m=re.search(r"nflasha(\d+)",ln)
    if m and ln.strip().startswith("#"): cur=int(m.group(1)); continue
    m=re.match(r"\s*(0x[0-9A-Fa-f]+),(0x[0-9A-Fa-f]+),(0x[0-9A-Fa-f]+),(0x[0-9A-Fa-f]+)",ln)
    if m and cur is not None:
        vals.append((cur,int(m.group(1),16),int(m.group(2),16))); cur=None
BOOT=0x400000
f=open("a7c_emmc_pt4.img","rb")
for num,st,sz in vals:
    if sz==0: continue
    f.seek(BOOT+st); d=f.read(sz)
    m=hashlib.md5(d).hexdigest(); z=(d.strip(b"\x00")==b"")
    p="parts/nflasha%d.bin"%num
    verdict="-no dump-"
    if os.path.exists(p):
        dd=open(p,"rb").read()
        pm=hashlib.md5(dd).hexdigest()
        if len(dd)==sz and pm==m: verdict="FULLMATCH dump=%d"%len(dd)
        elif hashlib.md5(d[:len(dd)]).hexdigest()==pm: verdict="DUMP-AT-START(len=%d < part=%d)"%(len(dd),sz)
        else:
            # maybe dump is zeros-padded inside image? check tail of dump zero or image tail zero
            tail_zero = d[len(dd):].strip(b"\x00")==b"" if sz>len(dd) else False
            verdict="HEADDIFF dump=%d"%len(dd)
            if tail_zero and hashlib.md5(d[:len(dd)]).hexdigest()==pm: verdict="MATCH+zeropad"
    print("nflasha%-3d off=%-10s size=%-11s imgmd5=%s allzero=%-5s %s"%(num,hex(st),hex(sz),m,z,verdict))
