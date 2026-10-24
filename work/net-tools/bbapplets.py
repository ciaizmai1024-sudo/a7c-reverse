import re,sys
d=open(sys.argv[1],'rb').read()
ver=re.search(rb'BusyBox v[0-9][^\x00]{0,40}',d)
print("VER:", ver.group(0).decode('latin1') if ver else "?", file=sys.stderr)
tok=re.compile(rb'^[a-zA-Z0-9_\[\]\./@+-]{1,20}$')
n=len(d)
seps=[m.start() for m in re.finditer(b'\x00',d)]
# collect runs of consecutive NUL-separated tokens
runs=[]; cur=[]; prev=-1
for s in seps:
    t=d[prev+1:s]
    if tok.match(t):
        cur.append(t.decode())
    else:
        if len(cur)>3: runs.append((prev+1,cur))
        cur=[]
    prev=s
if len(cur)>3: runs.append((prev+1,cur))
cands=[(o,r) for o,r in runs if len(r)>=40 and ('busybox' in r or 'ifconfig' in r or 'awk' in r)]
print("run sizes:",[len(r) for _,r in runs if len(r)>=15],"cands:",[(hex(o),len(r)) for o,r in cands],file=sys.stderr)
if cands:
    o,r=max(cands,key=lambda x:len(x[1]))
    print("chosen at",hex(o),file=sys.stderr)
    print("\n".join(sorted(set(r))))
else:
    # try fixed stride detection
    for stride in (8,12,16,20):
        pos=0; best=0; bestoff=0
        pat=re.compile(rb'^[a-z0-9_\[\]\.]{1,%d}\x00+$'%(stride-1))
        cnt=0; last=-stride
        for i in range(0,n-stride,stride):
            if pat.match(d[i:i+stride]):
                if i==last+stride: cnt+=1
                else:
                    if cnt>best: best,bestoff=cnt,i
                    cnt=1
                last=i
            else:
                if cnt>best: best,bestoff=cnt,i-stride
                cnt=0; last=-stride
        if best>30:
            names=[d[i:i+stride].split(b'\x00')[0].decode() for i in range(bestoff,bestoff+best*stride,stride)]
            print("stride",stride,"count",best,file=sys.stderr)
            print("\n".join(sorted(set(names))))
            break
