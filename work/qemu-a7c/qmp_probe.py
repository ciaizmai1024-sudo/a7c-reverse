#!/usr/bin/env python3
# Connect to QEMU QMP unix socket, sample PC/SP a few times, disassemble spin site.
import socket, json, sys, time

sock = socket.socket(socket.AF_UNIX)
sock.connect(sys.argv[1] if len(sys.argv) > 1 else "/home/wubin/qemu-a7c/mon.sock")
f = sock.makefile("rw")

def send(obj):
    f.write(json.dumps(obj) + "\r\n"); f.flush()

def read():
    line = f.readline()
    return json.loads(line) if line else None

read()  # greeting (QMP mode since -monitor unix without server,nowait? we pass qmp_caps anyway)
send({"execute": "qmp_capabilities"})
read()

def hmp(cmd):
    send({"execute": "human-monitor-command", "arguments": {"command-line": cmd}})
    while True:
        r = read()
        if r is None:
            return ""
        if "return" in r:
            return r["return"] or ""
        # ignore async events

for t in range(3):
    print("=== sample t=%d ===" % (t * 20))
    regs = hmp("info registers")
    # print only r0-r3,10-12,sp,pc,psr compactly
    keep = []
    for line in regs.splitlines():
        w = line.split()
        if any(k in line.lower() for k in ("r0 ", "r1 ", "r10", "sp ", "pc ", "psr", "r13", "r15")):
            keep.append(line.strip())
    print("\n".join(keep[:12]) if keep else regs[:400])
    print("-- pc x20 --")
    print(hmp("x /20i $pc")[:1200])
    time.sleep(20)
print("=== mtree grep ===")
print(hmp("info mtree")[:60])
