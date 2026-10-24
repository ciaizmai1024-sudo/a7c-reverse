import struct
def parse(f):
    d=open(f,'rb').read()
    shoff,=struct.unpack('<I',d[0x20:0x24]); shentsize,=struct.unpack('<H',d[0x2e:0x30])
    shnum,=struct.unpack('<H',d[0x30:0x32]); shstrndx,=struct.unpack('<H',d[0x32:0x34])
    raw=[]
    for i in range(shnum):
        e=d[shoff+i*shentsize:shoff+(i+1)*shentsize]
        name,typ,flags,addr,off,size,link,info,align,ent=struct.unpack('<IIIIIIIIII',e[:40])
        raw.append(dict(name=name,off=off,size=size,addr=addr,typ=typ,link=link,info=info,align=align,ent=ent))
    stroff=raw[shstrndx]['off']
    for s in raw:
        s['nm']=d[stroff+s['name']:d.index(b'\0',stroff+s['name'])].decode('latin1')
    return d,raw
def syms(d,S):
    out={}
    for sn in ('.dynsym','.symtab'):
        s=next((x for x in S if x['nm']==sn),None)
        if not s: continue
        st=S[s['link']]
        for i in range(s['size']//16):
            o=s['off']+i*16
            nm,info,other,shndx,val,sz=struct.unpack('<IBBHII',d[o:o+16])
            name=d[st['off']+nm:d.index(b'\0',st['off']+nm)].decode('latin1')
            out.setdefault((val&~1,shndx),name)
    return out
def cstr_at(d,S,va,maxlen=90):
    for s in S:
        if s['typ']==8: continue
        if s['addr']<=va<s['addr']+s['size']:
            raw=d[s['off']+va-s['addr']:]
            j=raw.find(b'\0'); b=raw[:min(j if j>=0 else maxlen,maxlen)]
            if len(b)>=3 and all(32<=c<127 for c in b): return b.decode('latin1')
    return None
