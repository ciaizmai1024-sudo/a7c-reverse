#!/usr/bin/env python3
"""ARM Thumb disassembler + ELF semantic annotator (libJiritsu.so analysis).

Self-contained ELF32 parser (no r2). Annotates:
  * PLT stubs -> imported symbol names (stub -> GOT slot -> .rel.plt)
  * GOT / .data / .bss slots -> symbol names (.rel.dyn / .dynsym)
  * literal-pool loads -> string contents / symbol names
  * branch/call targets -> PLT or local exported symbol names
Usage: python3 tools/jdis.py <elf> <start_hex> <end_hex>
"""
import sys, struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

PATH, START, END = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16)
B = open(PATH, 'rb').read()

e_phoff, = struct.unpack('<I', B[0x1c:0x20])
e_phentsize, e_phnum = struct.unpack('<HH', B[0x2a:0x2e])
e_shoff, = struct.unpack('<I', B[0x20:0x24])
e_shentsize, e_shnum, e_shstrndx = struct.unpack('<HHH', B[0x2e:0x34])

# ---------- segments (authoritative vaddr->fileoff) ----------
SEGS = []
for i in range(e_phnum):
    p = struct.unpack('<IIIIIIII', B[e_phoff + i * e_phentsize:e_phoff + (i + 1) * e_phentsize])
    if p[0] == 1:  # PT_LOAD
        SEGS.append(dict(vaddr=p[1], off=p[2], filesz=p[4], memsz=p[5]))

def v2p(v):
    for s in SEGS:
        if s['vaddr'] <= v < s['vaddr'] + s['filesz']:
            return s['off'] + (v - s['vaddr'])
    return None

# ---------- sections ----------
shs = [struct.unpack('<IIIIIIIIII', B[e_shoff + i * e_shentsize:e_shoff + (i + 1) * e_shentsize])
       for i in range(e_shnum)]
strtab_off = shs[e_shstrndx][4]
def nm_at(o):
    return B[strtab_off + o:B.index(b'\0', strtab_off + o)].decode('latin1')
SEC = {}
for s in shs:
    SEC[nm_at(s[0])] = dict(name=nm_at(s[0]), type=s[1], flags=s[2], addr=s[3], off=s[4],
                            size=s[5], link=s[6], info=s[7], align=s[8], entsize=s[9])
def sh(n):
    return SEC.get(n)

def rd32(v):
    p = v2p(v)
    return struct.unpack('<I', B[p:p + 4])[0] if p is not None and p + 4 <= len(B) else None

def cstr(v, n=256):
    p = v2p(v)
    if p is None:
        return None
    e = B.index(b'\0', p)
    t = B[p:min(e, p + n)]
    try:
        s = t.decode('utf-8')
    except Exception:
        return None
    return s if s and all(32 <= ord(c) < 127 for c in s) else None

# ---------- symbols ----------
STR = sh('.dynstr')
def symstr(i):
    o = STR['off'] + i
    return B[o:B.index(b'\0', o)].decode('utf-8', 'replace')

SYMTAB = sh('.dynsym')
syms = []
if SYMTAB:
    for i in range(SYMTAB['size'] // SYMTAB['entsize']):
        o = SYMTAB['off'] + i * SYMTAB['entsize']
        # NOTE: this Sony ELF uses a nonstandard Elf32_Sym field order:
        #   st_name(I) st_value(I) st_size(I) [info(B) other(B) shndx(H)](I)
        nm, value, size, misc = struct.unpack('<4I', B[o:o + 16])
        info, other, shndx = misc & 0xff, (misc >> 8) & 0xff, (misc >> 16) & 0xffff
        syms.append((symstr(nm), value, size, shndx, info))
symval = {}
for n, v, sz, shx, info in syms:
    if v:
        symval.setdefault(v & ~1, n)

# ---------- relocations ----------
relplt, reldyn = {}, {}
for sec in ('.rel.plt', '.rel.dyn'):
    s = sh(sec)
    if not s:
        continue
    tgt = relplt if sec == '.rel.plt' else reldyn
    for i in range(s['size'] // 8):
        off, info = struct.unpack('<2I', B[s['off'] + i * 8:][:8])
        tgt[off] = (syms[info >> 8][0] if (info >> 8) < len(syms) else f'sym{info >> 8}', info & 0xff)

# PLT stubs: 3 ARM words  add ip,pc,#lo / add ip,ip,#hi / ldr pc,[ip,#off]!
def _rot(w):
    r = (w >> 8) & 0xf
    i = w & 0xff
    return i if r == 0 else ((i >> (2 * r)) | (i << (32 - 2 * r))) & 0xffffffff

def _regs(w):
    return ((w >> 16) & 0xf), ((w >> 12) & 0xf)  # rn, rd

plt = sh('.plt')
stub, stubgot = {}, {}
if plt:
    a = plt['addr'] + 0x14
    while a + 12 <= plt['addr'] + plt['size']:
        w1, w2, w3 = struct.unpack('<3I', B[v2p(a):v2p(a) + 12])
        if _regs(w1) == (15, 12) and _regs(w2) == (12, 12) and _regs(w3) == (12, 15):
            got = (a + 8) + _rot(w1) + _rot(w2) + (w3 & 0xfff)
            stubgot[a] = got
            stub[a] = relplt.get(got, (f'GOT{got:#x}', 0))[0]
            a += 12
        else:
            a += 4

gotname, dataname = {}, {}
got, bss, data = sh('.got'), sh('.bss'), sh('.data')
for a, (nm, t) in reldyn.items():
    if got and got['addr'] <= a < got['addr'] + got['size']:
        gotname[a] = nm
    elif nm:
        dataname[a] = nm
for n, v, sz, shx, info in syms:
    if v and bss and bss['addr'] <= (v & ~1) < bss['addr'] + max(bss['size'], 0x40):
        dataname[v & ~1] = n

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
pool, baseregs = {}, {}
addr = START
while addr < END:
    p = v2p(addr)
    if p is None:
        print(f'{addr:#07x}  <unmapped>')
        addr += 2
        continue
    try:
        ins = next(md.disasm(B[p:p + min(10, END - addr)], addr))
    except StopIteration:
        print(f'{addr:#07x}  ??? undisasmable')
        addr += 2
        continue
    m, ops = ins.mnemonic, ins.op_str
    mb = m.split('.')[0]
    note = ''

    def ann(a, label=''):
        s = f'{label}{a:#x}'
        n = gotname.get(a) or dataname.get(a) or symval.get(a & ~1)
        if n:
            s += f' <{n}>'
        st = cstr(a)
        if st:
            s += f' = {st!r}'
        return s

    if mb == 'ldr' and '[pc' in ops:
        dst = ops.split(',')[0].strip()
        kk = ops.split('#')[-1].rstrip(']').strip()
        k = int(kk, 16) if kk else 0
        la = ((ins.address + 4) + k) & ~3
        val = rd32(la) or 0
        pool[dst] = val
        n = gotname.get(val) or dataname.get(val) or symval.get(val & ~1)
        st = cstr(val)
        note = f'  ;; pool {val:#x}' + (f' <{n}>' if n else '') + (f' = {st!r}' if st else '')
    elif mb == 'add' and 'pc' in ops:
        pp = [x.strip() for x in ops.split(',')]
        dst, src = pp[0], (pp[2] if len(pp) > 2 else pp[1])
        v = pool.get(src, pool.get(dst, 0))
        a = ins.address + 4 + v
        baseregs[dst] = a
        note = '  ;; ==> ' + ann(a)
    elif mb == 'adr':
        pp = [x.strip() for x in ops.split(',')]
        a = int(pp[1].lstrip('#'), 16)
        baseregs[pp[0]] = a
        note = '  ;; ==> ' + ann(a)
    elif mb in ('ldr', 'ldrb', 'ldrh', 'str', 'strb', 'strh') and '[' in ops and 'pc' not in ops:
        inner = ops[ops.index('[') + 1:ops.index(']')]
        pp = [x.strip() for x in inner.split(',')]
        b = pp[0]
        try:
            k = int(pp[1].lstrip('#'), 16) if len(pp) > 1 else 0
        except ValueError:
            k = None
        dst = ops.split(',')[0].strip()
        base = baseregs.get(b) or (pool[b] if b in pool and k is not None else None)
        if base and k is not None:
            a = base + k
            n = gotname.get(a) or dataname.get(a)
            note = f'  ;; *(a={a:#x})' + (f' <{n}>' if n else '')
            v = rd32(a)
            if v is not None and mb == 'ldr':
                note += f' = {v:#x}'
                n2 = gotname.get(v & ~1) or dataname.get(v & ~1) or symval.get(v & ~1)
                if n2:
                    note += f' <{n2}>'
                st = cstr(v) or cstr(a)
                if st:
                    note += f' -> {st!r}'
                pool[dst] = v
            elif n:
                note += '  /* &sym */'
    elif mb in ('bl', 'blx', 'b', 'bx'):
        try:
            t = int(ops.lstrip('#'), 16)
        except ValueError:
            t = None
        if t is not None:
            if t in stub:
                note = f'  ;; -> PLT {stub[t]}'
            elif t in symval:
                note = f'  ;; -> {symval[t & ~1]} @{t:#x}'
            else:
                note = f'  ;; -> {t:#x}'
    print(f'{ins.address:#07x}  {m:8s} {ops:34s}{note}')
    addr += ins.size or 2
