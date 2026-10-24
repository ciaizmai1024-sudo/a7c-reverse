import struct,json,sys
sys.path.insert(0,'/Users/wubin/pi-cwd/sony/a7creverse/work/modes')
from elfio import parse
def ror(v,n):
    n%=32
    return ((v>>n)|(v<<(32-n)))&0xffffffff if n else v
def build(f):
    d,S=parse(f)
    undef={}
    ds=next((s for s in S if s['nm']=='.dynsym'),None)
    st=next((s for s in S if s['nm']=='.dynstr'),None)
    if ds is None: return {}
    for i in range(ds['size']//16):
        o=ds['off']+i*16
        nm,info,other,shndx,val,sz=struct.unpack('<IBBHII',d[o:o+16])
        name=d[st['off']+nm:d.index(b'\0',st['off']+nm)].decode()
        undef[i]=name
    relmap={}
    for rp in [s for s in S if s['nm'] in ('.rel.plt','.rel.dyn')]:
        for i in range(rp['size']//8):
            o=rp['off']+i*8
            off,info=struct.unpack('<II',d[o:o+8])
            relmap.setdefault(off,undef.get(info>>8,'sym%d'%(info>>8)))
    plt=next(s for s in S if s['nm']=='.plt')
    found={}
    a=plt['addr']; end=plt['addr']+plt['size']
    def word(addr):
        return struct.unpack('<I',d[plt['off']+addr-plt['addr']:plt['off']+addr-plt['addr']+4])[0]
    while a+12<=end:
        w1,w2,w3=(word(a),word(a+4),word(a+8))
        if (w1>>20)==0xe28 and (w2>>20)==0xe28 and ((w3>>12)&0xf)==0xf and ((w3>>16)&0xf)==0xc and ((w3>>20)&0x1f)==0x1b:
            i1=(w1&0xfff); i2=(w2&0xfff)
            v1=ror(i1&0xff,2*(i1>>8)); v2=ror(i2&0xff,2*(i2>>8))
            v3=w3&0xfff
            U=(w3>>20)&1
            ip=((a+8)&~3)+v1+v2
            got=ip+(v3 if U else -v3)
            if got in relmap: found[a]=relmap[got]
        a+=4
    return found
if __name__=='__main__':
    for t in sys.argv[1:]:
        nm,p=t.split(':',1)
        f=build(p)
        json.dump({hex(k):v for k,v in sorted(f.items())},open('/Users/wubin/pi-cwd/sony/a7creverse/work/modes/plt_%s.json'%nm,'w'))
        uns=sorted(k for k,v in f.items() if v.startswith('sym'))
        print(nm,'stubs',len(f),'unresolved',len(uns))
