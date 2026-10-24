import struct, sys
p = sys.argv[1]; b = open(p,'rb').read()
et, em, ver, entry, phoff, shoff, flags, ehsize, phentsize, phnum, shentsize, shnum, shstrndx = struct.unpack_from('<HHIIIIIHHHHHH', b, 16)
print(f'type={et:#x} (3=ET_DYN) e_machine={em:#x} e_flags={flags:#x} entry={entry:#x}')
print(f'phoff={phoff:#x} phnum={phnum} shoff={shoff:#x} shnum={shnum} shstrndx={shstrndx} shentsize={shentsize}')
shs = [struct.unpack_from('<IIIIIIIIII', b, shoff+i*shentsize) for i in range(shnum)]
soff = shs[shstrndx][4]
def nm(n):
    e = b.index(b'\0', soff+n); return b[soff+n:e].decode('ascii','replace')
sec = {}
for i,s in enumerate(shs):
    sec[nm(s[0])] = s
print('\n-- 关键节 --')
for k in ['.interp','.dynsym','.dynstr','.hash','.gnu.hash','.dynamic','.text','.rodata','.data','.bss','.init','.fini','.ARM.extab','.ARM.exidx','.comment']:
    if k in sec:
        s = sec[k]; print(f'  {k:12} type={s[1]:#x} off={s[4]:#08x} size={s[5]:#07x} link={s[6]} entsize={s[9]}')
print('\n-- 程序头（哪些段可写：.dynamic 必须在可写段里）--')
for i in range(phnum):
    pht = struct.unpack_from('<IIIIIIII', b, phoff+i*phentsize)
    typ, off, va, fsz, msz, fl = pht[0], pht[1], pht[2], pht[3], pht[4], pht[6]
    print(f'  type={typ:#x} off={off:#08x} va={va:#08x} filesz={fsz:#07x} memsz={msz:#07x} flags={fl:#x}' + ('  <== RW' if fl==6 else ''))
ds = sec.get('.dynamic'); dn = sec.get('.dynstr'); sy = sec.get('.dynsym')
if ds and dn:
    base = dn[4]; print('\n-- .dynamic --')
    for i in range(0, ds[5], 8):
        tag, val = struct.unpack_from('<ii', b, ds[4]+i)
        if tag == 0: break
        s = ''
        if tag in (1,4,6,10,11,12,13,14,3):
            try:
                e = b.index(b'\0', base+val); s = ' "'+b[base+val:e].decode('ascii','replace')+'"'
            except Exception: pass
        print(f'  {tag:3} = {val:#x}{s}')
if sy and dn:
    strb = dn[4]; cnt = sy[5]//16
    defined, undef = [], []
    for i in range(cnt):
        o = sy[4]+i*16
        name, info, other, shndx, value, size = struct.unpack_from('<IBBBBI', b, o)  # ELF32 Sym: name(I) info(B) other(B) shndx(H) value(I) size(I)
        if name == 0: continue
        e = b.index(b'\0', strb+name); n = b[strb+name:e].decode('ascii','replace')
        bind, typ = info>>4, info & 0xf
        (undef if shndx == 0 else defined).append((bind, typ, shndx, value, size, n))
    print(f'\n-- .dynsym: {cnt} 项，定义 {len(defined)} / 引用 {len(undef)} --')
    print('  [导出/定义符号]')
    for bnd,typ,shndx,val,sz,n in defined[:120]:
        print(f'    bind={bnd} type={typ} shndx={shndx} val={val:#x} size={sz}  {n}')
    print('  [引用(Undef)前 60 个]')
    for bnd,typ,shndx,val,sz,n in undef[:60]:
        print(f'    {n}')
c = sec.get('.comment')
if c: print('\n.comment:', b[c[4]:c[4]+c[5]].decode('ascii','replace')[:200])
