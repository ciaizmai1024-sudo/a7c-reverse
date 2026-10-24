#!/usr/bin/env python3
"""Tiny ELF32 (ARM) inspector: string xrefs + capstone disassembly.

Usage:
  python3 elfutil.py syms   <elf> [regex]
  python3 elfutil.py xref   <elf> <literal-string>      # find code refs to string
  python3 elfutil.py dis    <elf> <addr> [nbytes] [arm|thumb]
  python3 elfutil.py funcs  <elf> [addr]                # symbol containing addr

Only ELF32 little-endian is supported (all camera userland here is ARM32).
"""
import re
import struct
import sys

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN

SHT_SYMTAB, SHT_DYNSYM, SHT_REL, SHT_RELA = 2, 11, 9, 4
SHF_EXECINSTR = 0x4
STT_FUNC = 2


class Elf:
    def __init__(self, path):
        self.path = path
        self.d = open(path, "rb").read()
        d = self.d
        assert d[:4] == b"\x7fELF" and d[4] == 1 and d[5] == 1, "need ELF32 LE"
        self.e_type, self.e_machine, _ver, self.e_entry, self.e_phoff, self.e_shoff, self.e_flags, \
            self.e_ehsize, self.e_phentsize, self.e_phnum, self.e_shentsize, self.e_shnum, \
            self.e_shstrndx = struct.unpack_from("<HHIIIIIHHHHHH", d, 16)
        self.secs = []
        for i in range(self.e_shnum):
            o = self.e_shoff + i * self.e_shentsize
            name, typ, flags, addr, off, size, link, info, align, entsize = \
                struct.unpack_from("<IIIIIIIIII", d, o)
            self.secs.append({"i": i, "name_off": name, "type": typ, "flags": flags,
                              "addr": addr, "off": off, "size": size, "link": link,
                              "info": info, "entsize": entsize})
        shstr = self.secs[self.e_shstrndx]
        base = shstr["off"]

        def sname(o):
            e = d.find(b"\0", base + o)
            return d[base + o:e].decode("latin1")
        for s in self.secs:
            s["name"] = sname(s["name_off"])
        self.phdrs = []
        for i in range(self.e_phnum):
            o = self.e_phoff + i * self.e_phentsize
            p_type, p_off, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = \
                struct.unpack_from("<IIIIIIII", d, o)
            self.phdrs.append({"type": p_type, "off": p_off, "vaddr": p_vaddr,
                               "filesz": p_filesz, "memsz": p_memsz, "flags": p_flags})
        self.syms = self._parse_syms(SHT_SYMTAB) + self._parse_syms(SHT_DYNSYM)
        self.syms.sort(key=lambda s: s["value"])
        self.relocs = self._parse_relocs()

    def _parse_syms(self, typ):
        out = []
        for s in self.secs:
            if s["type"] != typ or not s["entsize"]:
                continue
            strtab = self.secs[s["link"]]
            base, sbase = strtab["off"], s["off"]
            for o in range(sbase, sbase + s["size"], s["entsize"]):
                name, value, size, info, other, shndx = struct.unpack_from("<IIIBBH", self.d, o)
                e = self.d.find(b"\0", base + name)
                out.append({"name": self.d[base + name:e].decode("latin1"),
                            "value": value, "size": size, "info": info,
                            "type": info & 0xF, "shndx": shndx})
        return out

    def _parse_relocs(self):
        out = []
        for s in self.secs:
            if s["type"] not in (SHT_REL, SHT_RELA):
                continue
            for o in range(s["off"], s["off"] + s["size"], 8 if s["type"] == SHT_REL else 12):
                r_off, r_info = struct.unpack_from("<II", self.d, o)
                addend = struct.unpack_from("<i", self.d, o + 8)[0] if s["type"] == SHT_RELA else None
                out.append({"offset": r_off, "sym": r_info >> 8, "type": r_info & 0xFF,
                            "addend": addend, "where": s["name"]})
        return out

    def va2off(self, va):
        for p in self.phdrs:
            if p["vaddr"] <= va < p["vaddr"] + p["filesz"]:
                return p["off"] + (va - p["vaddr"])
        for s in self.secs:
            if s["addr"] and s["addr"] <= va < s["addr"] + s["size"] and s["type"] != 8:
                return s["off"] + (va - s["addr"])
        return None

    def off2va(self, off):
        for p in self.phdrs:
            if p["off"] <= off < p["off"] + p["filesz"]:
                return p["vaddr"] + (off - p["off"])
        for s in self.secs:
            if s["off"] <= off < s["off"] + s["size"] and s["type"] != 8:
                return s["addr"] + (off - s["off"])
        return None

    def exec_secs(self):
        return [s for s in self.secs if s["flags"] & SHF_EXECINSTR and s["size"]]

    def find_string(self, needle):
        return self.d.find(needle.encode())

    def xrefs_to_va(self, va):
        hits = []
        pat = struct.pack("<I", va)
        for s in self.secs:
            if s["type"] == 8:  # NOBITS
                continue
            data = self.d[s["off"]:s["off"] + s["size"]]
            pos = 0
            while True:
                i = data.find(pat, pos)
                if i < 0:
                    break
                hits.append((s["name"], s["addr"] + i, "const"))
                pos = i + 4
        for r in self.relocs:
            if r["addend"] == va:
                hits.append((r["where"], r["offset"], "reloc+%d" % r["type"]))
        return hits

    def func_at(self, addr):
        best = None
        for s in self.syms:
            v = s["value"] & ~1
            if s["type"] == STT_FUNC and v <= addr and (s["size"] and addr < v + s["size"] or
                                                        not s["size"] and addr - v < 0x4000):
                if best is None or v > (best["value"] & ~1):
                    best = s
        if best:
            return best
        for s in self.syms:
            v = s["value"] & ~1
            if v <= addr and (best is None or v > (best["value"] & ~1)):
                best = s
        return best

    def dis(self, addr, nbytes, mode=None):
        off = self.va2off(addr)
        if off is None:
            raise SystemExit("addr %#x not mapped" % addr)
        code = self.d[off:off + nbytes]
        if mode is None:
            sym = self.func_at(addr)
            mode = "thumb" if sym and (sym["value"] & 1) else "arm"
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if mode == "thumb" else CS_MODE_ARM)
        md.detail = True
        return mode, list(md.disasm(code, addr))


def main():
    cmd = sys.argv[1]
    e = Elf(sys.argv[2])
    if cmd == "syms":
        pat = re.compile(sys.argv[3]) if len(sys.argv) > 3 else None
        for s in e.syms:
            if s["type"] == STT_FUNC and (not pat or pat.search(s["name"])):
                print("%08x %5d %s" % (s["value"] & ~1, s["size"], s["name"]))
    elif cmd == "funcs":
        addr = int(sys.argv[3], 0) if len(sys.argv) > 3 else None
        if addr is None:
            for s in e.syms:
                if s["type"] == STT_FUNC:
                    print("%08x %5d %s" % (s["value"] & ~1, s["size"], s["name"]))
        else:
            f = e.func_at(addr)
            print(f)
    elif cmd == "xref":
        needle = sys.argv[3]
        off = e.find_string(needle)
        if off < 0:
            raise SystemExit("string not found")
        va = e.off2va(off)
        print("string %r file=0x%x va=%#x" % (needle, off, va))
        for sec, a, kind in e.xrefs_to_va(va):
            f = e.func_at(a)
            print("  %-10s %08x %-10s func=%s+0x%x (%s)" % (
                sec, a, kind, f["name"] if f else "?", a - (f["value"] & ~1) if f else 0,
                "0x%x" % (f["value"] & ~1) if f else "?"))
    elif cmd == "dis":
        addr = int(sys.argv[3], 0)
        n = int(sys.argv[4], 0) if len(sys.argv) > 4 else 128
        mode = sys.argv[5] if len(sys.argv) > 5 else None
        m, ins = e.dis(addr, n, mode)
        print("; %s mode=%s" % (e.path, m))
        f = e.func_at(addr)
        if f:
            print("; func %s+0x%x" % (f["name"], addr - (f["value"] & ~1)))
        for i in ins:
            print("%08x  %-8s %s %s" % (i.address, i.bytes.hex(), i.mnemonic, i.op_str))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
