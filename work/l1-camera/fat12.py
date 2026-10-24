#!/usr/bin/env python3
"""Standalone FAT12 reader for Sony nflasha1 (bare FAT volume, no MBR).
Usage: fat12.py <image> [bpb|ls [dirpath]|extract <name> <out>|map|fatchain]"""
import struct, sys, os, hashlib

def u8(b,o): return b[o]
def u16(b,o): return struct.unpack_from('<H',b,o)[0]
def u32(b,o): return struct.unpack_from('<I',b,o)[0]

class Fat12:
    def __init__(self, path):
        self.data = open(path,'rb').read()
        b = self.data
        assert b[510:512] == b'\x55\xaa', 'no boot sig'
        self.jmp = b[:3]
        self.oem = b[3:11]
        self.bps = u16(b,11)             # bytes per sector
        self.spc = u8(b,13)              # sectors per cluster
        self.rsvd = u16(b,14)            # reserved sectors
        self.nfat = u8(b,16)             # FAT copies
        self.rootent = u16(b,17)         # root dir entries
        self.tsect = u16(b,19)           # total sectors (16)
        self.media = u8(b,21)
        self.fatsize = u16(b,22)         # sectors per FAT
        self.secspt = u16(b,24)          # sectors per track
        self.heads = u16(b,26)
        self.hidd = u32(b,28)            # hidden sectors
        self.btsect = u32(b,60)          # large total sectors if tsect==0
        self.total = self.tsect if self.tsect else self.btsect
        self.root_dir_bytes = self.rootent*32
        self.fat_start = self.rsvd*self.bps
        self.root_start = self.fat_start + self.nfat*self.fatsize*self.bps
        self.data_start = self.root_start + self.root_dir_bytes
        # FAT type
        ccount = (self.total - self.rsvd - self.nfat*self.fatsize) // self.spc
        if ccount < 4085: self.fatty='FAT12'
        elif ccount < 65525: self.fatty='FAT16'
        else: self.fatty='FAT32'
        self.ccount = ccount
        self.fat = b[self.fat_start:self.fat_start+self.fatsize*self.bps]

    def entry(self, n):
        if n < 2: return 0
        # FAT12: 3 bytes per 2 entries
        off = n + n//2
        if off+2 > len(self.fat): return 0
        v = u16(self.fat, off)
        if n & 1:
            v = (v >> 4) & 0xFFF
        else:
            v &= 0xFFF
        if v >= 0xFF8: v = 0x0FFFFFFF  # EOF marker sentinel
        return v

    def chain(self, c):
        out=[c]; seen={c}
        while True:
            n=self.entry(out[-1])
            if n in (0,0x0FFFFFFF) or n in seen or n<2: break
            out.append(n); seen.add(n)
        return out

    def cluster_bytes(self, c):
        off = self.data_start + (c-2)*self.spc*self.bps
        return self.data[off:off+self.spc*self.bps]

    def file_bytes(self, c):
        out=bytearray()
        for cl in self.chain(c):
            out += self.cluster_bytes(cl)
        return bytes(out)

    def dir_entries(self, c=None):
        """c=None -> root dir (fixed area)."""
        if c is None:
            raw = self.data[self.root_start:self.root_start+self.root_dir_bytes]
        else:
            raw = self.file_bytes(c)
        ents=[]
        lfn=[]
        for i in range(0,len(raw),32):
            e=raw[i:i+32]
            if e[0]==0: break
            if e[0]==0xE5: continue
            if e[11]==0x0F:  # LFN fragment
                lfn.append(e); continue
            name=e[:11]
            attr=e[11]
            lname=''
            if lfn:
                frags=lfn
                parts=[]
                for x in frags:
                    for o in (1,14,26):
                        seg=x[o:o+10] if o==1 else x[o:o+12]
                        if seg==b'\xff'*len(seg): continue
                        for s in seg.decode('utf-16-le','ignore').split('\x00'):
                            keep=''.join(ch for ch in s if 0x20 <= ord(ch) < 0x7F)
                            if keep: parts.append(keep)
                lname=''.join(parts)
            lfn=[]
            cstart=(u16(e,26)) | (u16(e,20)<<16)
            size=u32(e,28)
            ents.append(dict(name=(lname or name.decode('latin1').rstrip()), sfn=name.decode('latin1'), attr=attr,cluster=cstart,size=size,                             mtime=u16(e,22),mdate=u16(e,24),
                             ctime=u16(e,14),cdate=u16(e,16),
                             raw=e.hex()))
        return ents

    @staticmethod
    def dt(d,t):
        y=((d>>9)&0x7F)+1980; mo=(d>>5)&0xF; dd=d&0x1F
        h=(t>>11)&0x1F; mi=(t>>5)&0x3F; s=(t&0x1F)*2
        return f"{y:04d}-{mo:02d}-{dd:02d} {h:02d}:{mi:02d}:{s:02d}"

def main():
    img=sys.argv[1]; mode=sys.argv[2] if len(sys.argv)>2 else 'bpb'
    f=Fat12(img)
    if mode=='bpb':
        b=f.data
        print("jump/label :",f.jmp.hex(), b[3:11].decode('latin1').strip() or '(none)')
        print("OEM name   :",f.oem.decode('latin1'))
        print(f"bytes/sector       = {f.bps}")
        print(f"sectors/cluster    = {f.spc}")
        print(f"reserved sectors   = {f.rsvd}")
        print(f"FAT copies         = {f.nfat}")
        print(f"root dir entries   = {f.rootent} ({f.root_dir_bytes} B)")
        print(f"sectors/FAT        = {f.fatsize}")
        print(f"sectors/track      = {f.secspt}, heads = {f.heads}")
        print(f"media descriptor   = 0x{f.media:02x}")
        print(f"hidden sectors     = {f.hidd}")
        print(f"total sectors(16b) = {f.tsect}  (32b @60 = {f.btsect})")
        print(f"FAT start off      = 0x{f.fat_start:x}; root dir off = 0x{f.root_start:x}; data start = 0x{f.data_start:x}")
        print(f"data clusters      = {f.ccount} -> FAT type = {f.fatty}")
        print(f"image size         = {len(f.data)} (total*bps = {f.total*f.bps})")
        for n in (0,1,2,0xFF,0xFF6,0xFF7,0xFFF,0xFF8,0xFFF8):
            print(f"  FAT[{n:#x}] = {f.entry(n) if n<2 or n>=0xFF else hex(f.entry(n))}")
        # FSInfo / backup boot (FAT32 style) presence
        print("sector1 sig @510:", b[0x200+510:0x200+512].hex(), "FSInfo sig:", b[0x200+416:0x200+420].hex(), "bootsector sig:", f.data[0x400:0x402].hex() if len(f.data)>0x402 else '-')
    elif mode=='ls':
        path=sys.argv[3] if len(sys.argv)>3 else '/'
        if path=='/':
            ents=f.dir_entries(None)
        else:
            # find subdir cluster by walking
            parts=[p for p in path.split('/') if p]
            cl=None; ents=None
            ents=f.dir_entries(None)
            for p in parts:
                e=[x for x in ents if norm(x['name'])==norm(p)]
                if not e: print('not found',p); return
                cl=e[0]['cluster']; ents=f.dir_entries(cl)
        for e in ents:
            t=Fat12.dt(e['cdate'],e['ctime']); m=Fat12.dt(e['mdate'],e['mtime'])
            print(f"{e['name']:<14} attr={e['attr']:#04x} cluster={e['cluster']:<5} chainlen={len(f.chain(e['cluster'])) if e['cluster']>=2 else 0:<4} size={e['size']:<9} created={t} mtime={m} dir={'Y' if e['attr']&0x10 else 'N'}")
    elif mode=='extract':
        name=sys.argv[3]; outp=sys.argv[4]
        # resolve path like /boot/vmlinux.bin
        parts=[p for p in name.split('/') if p]
        ents=f.dir_entries(None)
        cl=None
        for i,p in enumerate(parts):
            m=[x for x in ents if norm(x['name'])==norm(p) or norm(x['sfn'])==norm(p).replace('.','')]
            if not m: print('not found',p); return
            e=m[0]
            if i==len(parts)-1:
                data=f.file_bytes(e['cluster'])[:e['size']]
                os.makedirs(os.path.dirname(outp) or '.', exist_ok=True)
                open(outp,'wb').write(data)
                print(f"wrote {outp} len={len(data)} sha256={hashlib.sha256(data).hexdigest()} md5={hashlib.md5(data).hexdigest()} cluster={e['cluster']} chain={f.chain(e['cluster'])[:6]}{'...' if len(f.chain(e['cluster']))>6 else ''}")
            else:
                cl=e['cluster']; ents=f.dir_entries(cl)
    elif mode=='map':
        # print allocation summary: last used cluster, free clusters
        used=set(); i=2
        # scan all dirs & files
        def walk(c, path):
            for e in f.dir_entries(c):
                if e['attr']&0x10:
                    print(f"DIR  {path}/{e['name']} cl={e['cluster']} chain={len(f.chain(e['cluster']))}")
                    walk(e['cluster'], path+'/'+e['name'])
                else:
                    ch=f.chain(e['cluster'])
                    print(f"FILE {path}/{e['name']} cl={e['cluster']} nclus={len(ch)} lastcl={ch[-1]} size={e['size']}")
        walk(None,'')
    elif mode=='fatchain':
        n=int(sys.argv[3],0)
        print(f.chain(n))
    elif mode=='lastused':
        # enumerate every cluster reachable from root; report max & coverage
        reach=set()
        def walk(c):
            for e in f.dir_entries(c):
                if e['cluster']>=2:
                    for x in f.chain(e['cluster']): reach.add(x)
                    if e['attr']&0x10: walk(e['cluster'])
        walk(None)
        print("reachable clusters:",len(reach),"max:",max(reach),"min:",min(reach))
        missing=[c for c in range(2,max(reach)+1) if c not in reach]
        print("gaps inside range:",len(missing), missing[:20])
        # FAT entries nonzero
        nz=[n for n in range(2,f.ccount+2) if f.entry(n) not in (0,)]
        print("nonzero FAT entries:",len(nz),"max nonzero:",max(nz))
def norm(s):
    return s.upper().strip()
if __name__=='__main__':
    main()
