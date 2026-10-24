#!/usr/bin/env python3
"""Thumb 反汇编 + 字面量池解析（比 r2 自动注释可靠）。

模式（arm thumb 常见）：
  ldr rN,[pc,#k]      ; rN = 池中的偏移/绝对值
  add rN, pc          ; rN = rN + pc  → 字符串/数据地址
  ldr rN,[rM,#k]      ; rM 已知基址时，读取 *(base+k)

用法: python3 tools/dis.py <elf> <start_hex> <end_hex>
"""
import sys, struct, subprocess
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

path, s, e = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16)
data = open(path, 'rb').read()

def sh(name, args, pre=()):
    return subprocess.run(['r2', '-q', '-a', 'arm', '-b', '4', '-e', 'scr.color=0',
                           '-c', ';'.join(list(pre) + list(args)), path],
                          capture_output=True, text=True).stdout

secs = []
for line in sh(None, ['iS']).splitlines():
    p = line.split()
    if len(p) >= 7 and p[0].isdigit() and p[1].startswith('0x'):
        try:
            secs.append(dict(paddr=int(p[1], 16), size=int(p[2], 16), vaddr=int(p[3], 16),
                             vsize=int(p[4], 16), name=p[-1]))
        except ValueError:
            pass
def v2p(v):
    for x in secs:
        if x['vaddr'] <= v < x['vaddr'] + max(x['vsize'], x['size']):
            return x['paddr'] + (v - x['vaddr'])
    return None
def cstr(v, n=90):
    p = v2p(v)
    if p is None: return None
    raw = bytearray()
    while p < len(data) and data[p] and len(raw) < n:
        raw.append(data[p]); p += 1
    if len(raw) < 2: return None
    try: t = raw.decode('utf-8')
    except Exception: return None
    return t if all(32 <= ord(c) < 127 for c in t) else None

names = {}
for line in sh(None, ['aa', 'aac', 'afl']).splitlines():
    p = line.split()
    if len(p) >= 4 and p[0].startswith('0x') and p[1].isdigit():
        names[int(p[0], 16)] = p[-1]
for line in sh(None, ['aa', 'aac', "af@.", 'axt?']).splitlines():
    pass
try:  # 数据符号（bss/data 全局名）
    out = subprocess.run(['rabin2', '-E', path], capture_output=True, text=True).stdout
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 10 and p[0].isdigit():
            try: v = int(p[3], 16)
            except ValueError: continue
            if v and 'name' not in p[9]: names.setdefault(v, p[9])
except Exception:
    pass

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
pool = {}    # reg -> 池中读到的值
base = {}    # reg -> 已解析的绝对地址
lines = []
for ins in md.disasm(data[s:e], s):
    m, ops, note = ins.mnemonic, ins.op_str, ''
    def reg_of(x): return x.strip()
    if m == 'ldr' and '[pc' in ops:
        dst = ops.split(',')[0].strip()
        k = ops.split('#')[-1].strip().rstrip(']')
        k = int(k, 16) if k else 0
        la = ((ins.address + 4) + k) & ~3
        val = struct.unpack('<I', data[v2p(la):v2p(la) + 4])[0] if v2p(la) else 0
        pool[dst] = val
        st = cstr(val)
        note = f'  ;; 池值={val} ({val:#x})' + (f' -> {st!r}' if st else '')
        if val < 0x400: base[dst] = None
    elif m == 'add' and ops.count(',') == 1 and 'pc' in ops:
        dst = ops.split(',')[0].strip()
        v = pool.get(dst)
        if v is not None:
            a = ins.address + 4 + v
            st = cstr(a)
            base[dst] = a
            note = f'  ;; ==> {a:#x}' + (f' = {st!r}' if st else '')
    elif m == 'add' and 'pc' in ops and ops.count(',') == 2:
        p = [x.strip() for x in ops.split(',')]
        dst, src = p[0], p[2]
        v = pool.get(src) or pool.get(dst)
        if v:
            a = ins.address + 4 + v
            st = cstr(a)
            base[dst] = a
            note = f'  ;; ==> {a:#x}' + (f' = {st!r}' if st else '')
    elif m == 'ldr' and '[' in ops and 'pc' not in ops:
        inner = ops[ops.index('[') + 1:ops.index(']')]
        pp = [x.strip() for x in inner.split(',')]
        b = pp[0]
        try:
            k = int(pp[1].replace('#', '').replace('0x', '').rstrip(']'), 16) if len(pp) > 1 else 0
        except ValueError:
            lines.append(f'{ins.address:#07x}  {m:8s} {ops:34s}  ;; [reg+reg]')
            continue
        dst = ops.split(',')[0].strip()
        if base.get(b):
            a = base[b] + k
            pv = struct.unpack('<I', data[v2p(a):v2p(a) + 4])[0] if v2p(a) else 0
            st = cstr(pv) or cstr(a)
            pool[dst] = pv
            note = f'  ;; *({a:#x}) = {pv:#x}' + (f' -> {st!r}' if st else '')
            if pv < 0x400: pool[dst] = pv
        elif b in pool and pool[b] and v2p(pool[b] + k):
            a = pool[b] + k
            pv = struct.unpack('<I', data[v2p(a):v2p(a) + 4])[0]
            st = cstr(pv) or cstr(a)
            pool[dst] = pv
            note = f'  ;; *({a:#x}) = {pv:#x}' + (f' -> {st!r}' if st else '')
    elif m in ('bl', 'blx'):
        try:
            t = int(ops.replace('#', '').replace('0x', ''), 16)
            note = f'  ;; -> {names[t]}' if t in names else ''
        except ValueError:
            note = ''
    elif m == 'str' and base.get(ops.split('[')[1].split(',')[0].strip() if '[' in ops else ''):
        note = ''
    if m.startswith('st') and '[' in ops:
        inner = ops[ops.index('[') + 1:ops.index(']')]
        b = inner.split(',')[0].strip()
        if base.get(b): note = f'  ;; [r{b[-1]}] 基址 {base[b]:#x}'
    lines.append(f'{ins.address:#07x}  {m:8s} {ops:34s}{note}')
print('\n'.join(lines))
