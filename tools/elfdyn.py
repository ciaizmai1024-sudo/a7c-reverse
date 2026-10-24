#!/usr/bin/env python3
"""ELF32(ARM) 动态符号速查：谁定义 / 谁引用 / DT_NEEDED。
用法:  python3 tools/elfdyn.py <文件或目录> [...] [--want sym, sym]
"""
import struct, os, sys, glob


def secs_of(d):
    e_shoff, = struct.unpack_from('<I', d, 0x20)
    stride, = struct.unpack_from('<H', d, 0x2e)
    n, = struct.unpack_from('<H', d, 0x30)
    hs = [struct.unpack_from('<10I', d, e_shoff + i * stride)
          for i in range(n) if e_shoff + i * stride + 40 <= len(d)]
    cands = [h for h in hs if h[1] == 3]
    # .shstrtab：内容里含 '.shstrtab' 或 '.dynsym' 的那个（常有多个 SHT_STRTAB）
    shstr = None
    for h in cands:
        blob = d[h[4]:h[4] + h[5]]
        if b'.shstrtab' in blob or b'.dynsym' in blob:
            shstr = h
            break
    if shstr is None:
        shstr = cands[-1] if cands else None
    if shstr is None:
        return []
    out = []
    for h in hs:
        o = shstr[4] + h[0]
        e = d.find(b'\0', o)
        out.append((d[o:e].decode('ascii', 'replace'), h))
    return out


def info(path):
    d = open(path, 'rb').read()
    if d[:4] != b'\x7fELF':
        return None
    S = secs_of(d)
    dynstr = next((h for nm, h in S if nm == '.dynstr'), None) \
        or next((h for nm, h in S if nm == '.strtab'), None)
    undef, dfn, needed = set(), set(), set()
    for nm, h in S:
        if nm in ('.dynsym', '.symtab') and h[9] and dynstr:
            sb = d[dynstr[4]:dynstr[4] + dynstr[5]]
            for j in range(h[5] // h[9]):
                o = h[4] + j * h[9]
                if o + 16 > len(d):
                    break
                st_name, val, size, inf, other, shndx = struct.unpack_from('<3IBBH', d, o)
                if not st_name:
                    continue
                z = sb.find(b'\0', st_name)
                if z < 0:
                    continue
                s = sb[st_name:z].decode('ascii', 'replace')
                if s:
                    (undef if shndx == 0 else dfn).add(s)
        if nm == '.dynamic' and dynstr:
            sb = d[dynstr[4]:dynstr[4] + dynstr[5]]
            o = h[4]
            while o + 8 <= len(d):
                tag, val = struct.unpack_from('<2I', d, o)
                o += 8
                if tag == 0:
                    break
                if tag == 1:
                    z = sb.find(b'\0', val)
                    if z > 0:
                        needed.add(sb[val:z].decode())
    return undef, dfn, needed


def collect(paths):
    fs = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, fl in os.walk(p):
                fs += [os.path.join(root, f) for f in fl]
        else:
            fs.append(p)
    out = {}
    for f in fs:
        r = info(f)
        if r:
            out[f] = r
    return out


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--want')]
    want = []
    for a in sys.argv[1:]:
        if a.startswith('--want'):
            want = a.split('=', 1)[1].split(',') if '=' in a else \
                ['RSA_verify', 'PEM_read_RSA_PUBKEY', 'SHA1_Init', 'SHA1_Final',
                 'SHA256', 'RSA_free', 'RSA_size', 'EVP_aes_256_cbc', 'RSA_sign']
    cache = collect(args)
    print('解析成功的 ELF 数 = %d' % len(cache))
    for t in want:
        defs = sorted(os.path.basename(f) for f, (u, dv, nd) in cache.items() if t in dv)
        refs = sorted(os.path.basename(f) for f, (u, dv, nd) in cache.items() if t in u)
        print('%-22s DEF=%-34s REF=%s' % (t, ','.join(defs) or '-', ','.join(refs) or '-'))
    for f, (u, dv, nd) in sorted(cache.items()):
        if os.path.basename(f) in ('sauu', 'sdfileinput.elf', 'mf', 'sauu -m'):
            ck = lambda S: sorted(x for x in S
                                  if any(k in x for k in
                                         ('RSA', 'SHA1', 'SHA2', 'EVP', 'PEM', 'BN_', 'MD5', 'AES', 'ign', 'erify')))
            print('\n>> %s' % f)
            print('   NEEDED      : %s' % ', '.join(sorted(nd)))
            print('   加密类 UNDEF: %s' % ', '.join(ck(u)[:14]))
            print('   加密类 DEF  : %s' % ', '.join(ck(dv)[:14]))
