import re,subprocess,sys,struct
f=open("backup_l1.ko","rb").read()
e_shoff=struct.unpack_from("<I",f,0x20)[0]; e_shentsize=struct.unpack_from("<H",f,0x2e)[0]; e_shnum=struct.unpack_from("<H",f,0x30)[0]; e_shstrndx=struct.unpack_from("<H",f,0x32)[0]
so=e_shoff+e_shstrndx*e_shentsize
shstr_off=struct.unpack_from("<I",f,so+0x10)[0]
secs={}; rels={}; order=[]
for i in range(e_shnum):
    o=e_shoff+i*e_shentsize
    nm,typ,off,size,link,info=struct.unpack_from("<IIIIII",f,o)[:6]
    entsize=struct.unpack_from("<I",f,o+0x28)[0]
    name=f[shstr_off+nm:shstr_off+nm+64].split(b"\x00")[0].decode()
    secs[name]=(off,size); order.append(name)
    if typ==9: rels[name]=(off,size,info,link,entsize or 8)
ti=order.index(".text")
symtab_off,symtab_size=secs[".symtab"]; strtab_off,_=secs[".strtab"]
def symname(si):
    o=symtab_off+si*16
    nm,va,sz,info,other,shndx=struct.unpack_from("<IIIBBH",f,o)
    s=f[strtab_off+nm:strtab_off+nm+128].split(b"\x00")[0].decode()
    return s,va,shndx
relmap={}
for name,(off,size,info,link,entsize) in rels.items():
    if info==ti:
        for j in range(size//entsize):
            r_off,r_info=struct.unpack_from("<II",f,off+j*entsize)
            si=r_info>>8; rtype=r_info&0xff
            s,va,sh=symname(si)
            val=struct.unpack_from("<I",f,secs[".text"][0]+r_off)[0]
            relmap[r_off]=(s,va,val,rtype)
text_off,text_size=secs[".text"]
dis=subprocess.run(["arm-linux-gnueabi-objdump","-d","-j",".text","backup_l1.ko"],capture_output=True,text=True).stdout
out=[]
for line in dis.splitlines():
    out.append(line)
    m=re.match(r"^\s+([0-9a-f]+):\t([0-9a-f]{8})\s+(.*)",line)
    if m and "ldr" in m.group(3) and "[pc," in m.group(3):
        a=int(m.group(1),16); w=int(m.group(2),16)
        imm=w&0xfff; up=(w>>23)&1
        tgt=a+8+(imm if up else -imm)
        val=struct.unpack_from("<I",f,text_off+tgt)[0]
        r=relmap.get(tgt)
        info=f"@{hex(tgt)}={hex(val)}"
        if r: info+=f" -> {r[0]} symva={hex(r[1])} abs={hex(val+r[1])} type={r[3]}"
        # try to show string if it points into strtab
        if strtab_off<=val<strtab_off+symtab_size: pass
        out.append("\t\t; "+info)
open("text_ann.txt","w").write("\n".join(out))
print("ok")
