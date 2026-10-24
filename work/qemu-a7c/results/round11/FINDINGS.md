# Round 11 — backup.ko file_load root-cause, sauu crash chain, REAL partition write + reboot rehearsal

TL;DR: **A real write to /dev/nflasha23 through Sony's AL_EMMC driver succeeded and persisted
across a (simulated) reboot** — offline write+reboot rehearsal is GREEN. `backup.ko` file_load
still fails in QEMU; cookie mismatch alone is not the whole story. `sauu` cannot progress in
USER mode because mcmn_drv.ko (required by its mcmn_init path) depends on Backup_* symbols.

## Runs (remote: ~/qemu-a7c/results_round11/)
- `run_r11.sh <tag> <initrd> [wait]`, IMG env selects eMMC image.
- initrds: r11a (diag, md5 aea70435…), r11b (tmpfs reroute, 834a4e16…), r11c (cookie-patched native ko + mcmn insmod, f7f44d21…), r11d (bypass-patched, de1459e6…), r11e (syntax bug, a12f69da…), r11f (WORKING chain, 46025556…).
- eMMC test image: `a7c_emmc_r11c.img` md5 `8587674613a0ffd86beea010e74fd47c` (copy of pt4; now contains our written a23 data).

## Confirmed facts
1. **H3 true**: `Backup.bin` header `hdr+0x0c` = `"BK4\0"`; both module variants carry BK4/BK3/BK2 strings. Version string is NOT the failure.
2. **H1 nuance**: the `file_load` path itself (backupfile_load_file → vfs_stat/filp_open/vfs_read → Data_check → Data_init) makes **no OSAL IPC calls**; `ud_im.elf` runs (PID visible) yet file_load fails identically → OSAL server is not the load blocker.
3. tmpfs reroute (r11b): files byte-identical on tmpfs (`/mnt1`), failure identical → vfat/permission ruled out.
4. **Cookie constant**: initrd (rescue) backup.ko (md5 `0a38eec6…`) compares `hdr+4..7` (Data_GetCookie) against literal **0x9000e1a0** (5 occurrences, all comparators). Real `Backup.bin` cookie = `0xaaaaaaaa`; the **a15 product module (md5 638881c5…)** expects `0xaaaaaaaa` instead (its literal at 0x3f84). Binary-patching all 5 occurrences of 0x9000e1a0→0xaaaaaaaa in the native ko **still fails file_load** → the gate includes more than cookie (likely `Data_init` record-table checksum; count fields differ pri=2884 vs bak=2885 as expected).
5. **backup bypass experiment (r11d)**: patching native module's `backup_init` `bl backupfile_load` (rel at .init.text+0x148) and `bl backup_senser_init` (+0x1d0) to `mov r0,#0` let the module print `** NO SAVE MODE **` but then it page-faulted (pc≈module+0x3d4, jump through NULL function/table left by skipped file_load). So backup.ko has no soft-fail path; file_load success is mandatory for module residency.
6. **sauu crash chain solved**: `mcmn_log_init` (libInfraMediaCommon.so @0x1d00a) scans a node list whose base = **0xffffffff (MAP_FAILED sentinel)** because `mcmn_mmap_init` opens the mcmn device and the list is never backed. In USER mode nothing loads **mcmn_drv.ko** (insmod.sh never insmods it; execute_ufp only in MSCRYPT mode). Attempting it in QEMU USER mode fails: `mcmn_drv` has 7 undefined `Backup_*` symbols → hard dependency on a *loaded* backup.ko. So: backup file_load → backup symbols → mcmn_drv → mcmn mmap → sauu state machine. Single bottleneck = backup file_load.
7. **REAL WRITE (r11f/r11g)**: with original native backup.ko (load fails, as before) but full insmod chain (emmc.ko up), `dd` of a 64KiB urandom pattern to **/dev/nflasha23** (major 252, minor 23) returned RC=0 and read-back md5 matched immediately. After cold restart of QEMU, fresh boot-verify read `md5 = 5c5a00ecb1b502fed6d9253f18b5e98c` == pattern written in the previous run → **write persisted through reboot**. Host-side: pattern found at file offset **0x50C00000** of `a7c_emmc_r11c.img` (= 0x400000 mtd header + 0x50800000 raw a23 offset).
8. **Reboot path**: `ud_reboot.elf` RC=255 in QEMU (needs missing PMIC/LSI ioctl). busybox `reboot` triggers kernel `Restarting system.` (machine_restart runs) but the QEMU cxd90045 machine does not reset the machine — QEMU must be externally restarted for the "reboot" (remaining gap for a true one-process reboot demo; likely needs a reboot-exit hook in bionz.c or PMIC register emulation).
9. Exception monitor: after sauu's page fault the kernel enters `Exception>` monitor and swallows the console — scripts after a sauu crash never resume. Hence r11f moved the write+reboot phase *before* sauu (deviation).
10. busybox applets available: md5sum, cut, kill, sleep; **no cksum, no cmp, no timeout**.

## Remaining blockers for "sauu writes the partition" proper
- `backup.ko file_load` in QEMU: cookie is only part of it; next RE step is `Data_init` table validation (hdr+0x10 data base, hdr+0x10 records ×6 table) — likely a per-entry checksum/`Backup_get_state` gate. Also consider testing the **a15 product module** (expects aaaaaaaa cookie) against our file with matching ABI (r10 already noted ABI mismatch: initrd kernel exports differ).
- H2 (identical failure on real hardware) remains plausible: rescue initrd expects cookie 0x9000e1a0 which real files never have; real USER updates may run backup-degraded exactly as QEMU does — except real-hardware sauu also needs mcmn… which needs Backup symbols. Open question: how real A7C USER update avoids this (maybe real flow is MSCRYPT/service mode where mcmn_drv is insmoded, or a different initrd loads backup successfully).
- ud_reboot.elf / kernel restart under QEMU (machine reset hook).

## Deviations from real flow (this rehearsal)
- write triggered by manual dd (not sauu), reboot by busybox reboot + external QEMU restart (not ud_reboot.elf).
- execute_ufp.sh USER branch reordered (write+reboot before sauu) to dodge the exception monitor freeze.
- r11c/r11d tested binary-patched backup.ko copies (kept as initrd images; tree restored to pristine native ko md5 0a38eec6).

## Next-round suggestions (R12)
1. RE `Data_init` (native ko, init.text rel offsets known: file_load call+0xac…) to find the remaining check that fails after cookie patch; goal: unpatched-loadable backup.
2. Try a15 product backup.ko with initrd kernel: identify ABI gaps (nm undefined syms vs kernel exports) and shim them.
3. Add QEMU machine reboot support (exit-with-code on reboot or reset CPUs) in bionz.c/sd.c tree so `reboot` is observable end-to-end.
4. Then: backup→mcmn_drv→sauu (expect `BeginningState → WaitingConnectionState`), fake PC connection later via QEMU USB/UDC model or ud_* ioctl injection.
