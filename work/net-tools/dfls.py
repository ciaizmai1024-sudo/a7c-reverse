import subprocess, sys, re
DF="/opt/homebrew/opt/e2fsprogs/sbin/debugfs"
img=sys.argv[1]
root=sys.argv[2] if len(sys.argv)>2 else "/"
def ls(path):
    p=subprocess.run([DF,"-R",f"ls -l {path}",img],capture_output=True,text=True)
    rows=[]
    for ln in p.stdout.splitlines():
        parts=ln.split()
        if len(parts)<9: continue
        if not re.match(r'^\d+$',parts[0]) or not re.match(r'^[0-7]{5,6}$',parts[1]): continue
        m=int(parts[1],8); size=parts[5]; rest=parts[8:]
        if parts[6].startswith("1") or re.match(r'^\d\d-\w\w\w',parts[6]):
            pass
        name=" ".join(rest)
        typ="l" if (m & 0o170000)==0o120000 else ("d" if (m & 0o170000)==0o040000 else "f")
        rows.append((name,parts[1],size,typ))
    return rows
out=[]
def walk(path,depth=0):
    for name,mode,size,typ in ls(path):
        if name in (".",".."): continue
        nm=name.split(" -> ")[0]
        full=path.rstrip("/")+"/"+nm
        out.append("\t".join([full,mode,size,typ]))
        if typ=="d" and depth<10: walk(full,depth+1)
walk(root)
print("\n".join(out))
