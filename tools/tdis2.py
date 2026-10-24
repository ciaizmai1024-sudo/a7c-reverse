#!/usr/bin/env python3
"""ARM Thumb 反汇编 + ELF 语义注释（GOT 槽名 / PLT 桩名 / .bss+.data 全局名 / 字面量池字符串）。

自己解析 ELF32（不用 r2），因此注释来源可核对：
  * .rel.plt  -> PLT 桩地址 -> 导入函数名
  * .rel.dyn  -> GOT 槽 / .data 地址 -> 全局符号名（含 .bss 变量，如 firm_model）
  * 字面量池  -> ldr rN,[pc,#k]; (add rN,pc | ldr rN,[rN,#k]) -> 字符串 / 槽位名

用法: python3 tools/tdis2.py <elf> <start_hex> <end_hex> [--thumb16-start 0xADDR]
"""
import sys, struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

path, start, end = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16)
B = open(path, 'rb').read()

# ---------------- ELF32 段表（用 r2 的 iS，实测这些 Sony ELF 的头字段不可靠）----------------
import subprocess
S = []
for line in subprocess.run(['r2', '-q', '-a', 'arm', '-b', '4', '-e', 'scr.color=0', '-c', 'iS', path],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.splitlines():
    p = line.split()
    if len(p) >= 7 and p[0].isdigit() and p[1].startswith('0x'):
        try:
            S.append(dict(name=len(S), type=0, addr=int(p[3], 16), off=int(p[1], 16),
                          size=int(p[2], 16), vsize=int(p[4], 16), nm=p[-1]))
        except ValueError:
            pass
def secname(s):
    return s['nm']
def sh(nm):
    out = None
    for s in S:
        if secname(s) == nm: out = s
    return out
STR = next(s for s in S if secname(s) == '.dynstr')
def symstr(i):
    o = STR['off'] + i
    return B[o:B.index(b'\0', o)].decode()
SYMTAB = next((s for s in S if secname(s) == '.dynsym'), None)
syms = []
if SYMTAB:
    n = SYMTAB['size'] // 16
    for i in range(n):
        o = SYMTAB['off'] + i * 16
        nm, info, other, shndx, value, size = struct.unpack('<IBBHII', B[o:o + 16])
        syms.append((symstr(nm), value, size, shndx, info))

def v2p(v):
    for s in S:
        if s['addr'] <= v < s['addr'] + max(s.get('vsize', s['size']), s['size'], 1):
            return s['off'] + (v - s['addr'])
    return None
def rd32(v):
    p = v2p(v)
    return struct.unpack('<I', B[p:p + 4])[0] if p is not None else None
def cstr(v, n=100):
    p = v2p(v)
    if p is None: return None
    e = B.index(b'\0', p)
    t = B[p:min(e, p + n)]
    try: t = t.decode('utf-8')
    except Exception: return None
    return t if t and all(32 <= ord(c) < 127 for c in t) else None

# ---------------- 重定位 ----------------
relplt, reldyn = {}, {}
for sec in ('.rel.plt', '.rel.dyn'):
    s = sh(sec)
    if not s: continue
    tgt = relplt if sec == '.rel.plt' else reldyn
    for i in range(s['size'] // 8):
        off, info = struct.unpack('<2I', B[s['off'] + i * 8:][:8])
        sym, rtyp = info >> 8, info & 0xff
        nm = syms[sym][0] if sym < len(syms) else f'sym{sym}'
        tgt[off] = (nm, rtyp, sym)
# PLT 桩：第一个桩 = .plt + 0x14（前面 20 字节是 resolver），每个 12 字节，顺序 = .rel.plt 条目顺序
plt = sh('.plt')
stub = {}
if plt:
    addrs = sorted(relplt)
    for i, a in enumerate(addrs):
        stub[plt['addr'] + 0x14 + i * 12] = relplt[a][0]
# GOT 槽名：.rel.dyn 的 off 落在 .got/.data/.bss
gotname = {}
bssname = {}
got = sh('.got'); bss = sh('.bss'); data = sh('.data')
for a, (nm, t, sidx) in reldyn.items():
    if got and got['addr'] <= a < got['addr'] + got['size']:
        gotname[a] = nm
    elif bss and bss['addr'] <= a < bss['addr'] + max(bss['size'], 0x20000):
        bssname[a] = nm
    elif data and data['addr'] <= a < data['addr'] + data['size']:
        bssname[a] = nm
symval = {v: n for n, v, sz, shx, info in syms if v}

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
pool, baseregs = {}, {}
out = []
addr = start
while addr < end:
    it = md.disasm(B[addr:addr + 6], addr)
    try:
        ins = next(it)
    except StopIteration:
        addr += 2
        continue
    m, ops, note = ins.mnemonic, ins.op_str, ''
    def ann_addr(a, label=''):
        st = cstr(a)
        nm = gotname.get(a) or bssname.get(a) or symval.get(a)
        s = f'{label}{a:#x}'
        if nm: s += f' <{nm}>'
        if st: s += f' = {st!r}'
        return s
    if m == 'ldr' and '[pc' in ops:
        dst = ops.split(',')[0].strip()
        kk = ops.split('#')[-1].rstrip(']').strip()
        k = int(kk, 16) if kk else 0
        la = ((ins.address + 4) + k) & ~3
        p = v2p(la); val = struct.unpack('<I', B[p:p + 4])[0] if p else 0
        pool[dst] = val
        nm = gotname.get(val) or bssname.get(val) or symval.get(val)
        st = cstr(val)
        note = f'  ;; 池 {val:#x}' + (f' <{nm}>' if nm else '') + (f' = {st!r}' if st else '')
    elif m == 'add' and 'pc' in ops and ops.replace(' ', '').endswith('pc'):
        dst = ops.split(',')[0].strip()
        v = pool.get(dst, 0)
        a = ins.address + 4 + v
        baseregs[dst] = a
        note = '  ;; ==> ' + ann_addr(a)
    elif m == 'add' and 'pc' in ops:
        p = [x.strip() for x in ops.split(',')]
        dst, src = p[0], (p[2] if len(p) > 2 else p[1])
        v = pool.get(src, pool.get(dst, 0))
        a = ins.address + 4 + v
        baseregs[dst] = a
        note = '  ;; ==> ' + ann_addr(a)
    elif m == 'ldr' and '[' in ops and 'pc' not in ops:
        inner = ops[ops.index('[') + 1:ops.index(']')]
        pp = [x.strip() for x in inner.split(',')]
        b = pp[0]
        try:
            k = int(pp[1].lstrip('#'), 16) if len(pp) > 1 else 0
        except ValueError:
            out.append(f'{ins.address:#07x}  {m:8s} {ops:34s}  ;; [reg+reg]')
            continue
        dst = ops.split(',')[0].strip()
        if b in baseregs:
            a = baseregs[b] + k
            nm = gotname.get(a) or bssname.get(a)
            v = rd32(a)
            note = f'  ;; *({a:#x})' + (f' <{nm}>' if nm else '')
            if v is not None:
                note += f' = {v:#x}' + (f' <{gotname.get(v) or bssname.get(v)}>' if (gotname.get(v) or bssname.get(v)) else '')
                st = cstr(v)
                if st: note += f' -> {st!r}'
                pool[dst] = v
            if nm: note += f'   /* 取 {nm} 的地址 */'
        elif b in pool and pool[b]:
            a = pool[b] + k
            v = rd32(a)
            note = f'  ;; *({a:#x})'
            if v is not None:
                note += f' = {v:#x}'
                st = cstr(v) or cstr(a)
                if st: note += f' -> {st!r}'
                pool[dst] = v
    elif m in ('bl', 'blx'):
        try:
            t = int(ops.lstrip('#'), 16)
            nm = stub.get(t)
            note = f'  ;; -> PLT {nm}' if nm else (f'  ;; -> {symval.get(t, hex(t))}')
        except ValueError:
            note = ''
    if m.startswith(('str', 'ldrb', 'strb', 'ldr', 'ldrh', 'strh')) and '[' in ops and 'pc' not in ops:
        inner = ops[ops.index('[') + 1:ops.index(']')]
        b = inner.split(',')[0].strip()
        if b in baseregs and m not in ('ldr',):
            note = f'  ;; [{b}] = {baseregs[b]:#x}' + (f' <{gotname.get(baseregs[b])}>' if gotname.get(baseregs[b]) else '')
    out.append(f'{ins.address:#07x}  {m:8s} {ops:34s}{note}')
    addr += ins.size if ins.size else 2
print('\n'.join(out))
