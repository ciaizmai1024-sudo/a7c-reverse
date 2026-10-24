#!/usr/bin/env python3
"""Scan firmware trees for flag-file strings and report file/offset/string.

Usage: python3 scan_mode_refs.py <root> [<root>...]
Output: TSV on stdout (root, file, offset, arch, string)
"""
import os
import re
import struct
import sys

PAT = re.compile(
    rb"(?i)(/setting/[^\x00\r\n]{0,40}|/tmp/jmode|/tmp/jbusy|"
    rb"\bmode[0-9a-z]{0,3}\b|dmode|preload|MODE|getMode|setMode|checkMode|mode_switch|"
    rb"updater/mode|us_remove_modes|IAMUPDATER)")


def printable_runs(data, minlen=4):
    run = bytearray()
    start = 0
    for i, b in enumerate(data):
        if 0x20 <= b < 0x7f or b in (9,):
            if not run:
                start = i
            run.append(b)
        else:
            if len(run) >= minlen:
                yield start, bytes(run)
            run.clear()
    if len(run) >= minlen:
        yield start, bytes(run)


def elf_arch(data):
    if data[:4] != b"\x7fELF":
        return "not-elf"
    cls = data[4]
    machine = struct.unpack_from("<H", data, 18)[0]
    names = {40: "ARM", 183: "AARCH64", 3: "x86", 62: "x86_64", 8: "MIPS"}
    return "ELF%d:%s" % (32 if cls == 1 else 64, names.get(machine, str(machine)))


def main():
    for root in sys.argv[1:]:
        for dp, dns, fns in os.walk(root):
            for fn in fns:
                p = os.path.join(dp, fn)
                try:
                    data = open(p, "rb").read()
                except OSError:
                    continue
                rel = os.path.relpath(p, root)
                arch = elf_arch(data)
                for off, s in printable_runs(data):
                    if PAT.search(s):
                        print("%s\t%s\t0x%x\t%s\t%s" % (root, rel, off, arch,
                                                        s.decode("latin1")))


if __name__ == "__main__":
    main()
