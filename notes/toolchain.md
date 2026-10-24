# toolchain.md —— 交叉链接 libJit.so（实测通过）+ QEMU(CXD90045) 本机可行性

日期：本机 macOS/arm64，OrbStack 可用。以下每条都是实际跑过的命令与输出摘录。

---

## A. ARM32 共享库交叉链接 —— 已解决（OrbStack 容器内 GNU ld）

### A0. 失败根因
本机只有 Apple clang/ld。Apple ld 不认 GNU 选项（`-EL --hash-style=gnu --eh-frame-hdr -shared -soname`），
所以 `clang -target armv7-unknown-linux-gnueabi -shared` 必挂（编译 OK，链接挂）。`libJit.o` 本身没问题。

### A1. 本机工具链盘点（命令原文 + 结果）
```sh
brew list --formula | grep -iE "lld|binutils|musl|cross|qemu|gcc"   # → 空（brew 可用，7.0.10，但一个都没装）
ls /opt/homebrew/opt | grep -iE "llvm|lld|binutils|musl|qemu"       # → 空
ls /opt/homebrew/opt/llvm/bin/ld*                                   # → 不存在
find /opt/homebrew -maxdepth 4 -name "ld.lld*" -o -name "ld.gold"   # → 无（任何 ELF ld 都没有）
which qemu-system-arm qemu-arm                                      # → 无
python3 -c "import elftools"                                        # → ModuleNotFoundError（系统 py3；brew 还有 py3.12/13/14 亦未验证装 pyelftools）
which meson ninja pkg-config                                        # 只有 pkg-config
```
⇒ 本机没有任何能链 ELF32 ARM 的 linker。手写 ELF 链接器方案（pyelftools）不必动用——见下，容器 30 秒解决。

### A2. Docker/OrbStack（可用！）
```sh
ls /Applications | grep -i orbstack     # OrbStack.app
open -a OrbStack                        # 启动后 docker info 2 秒内就绪
docker info | grep -E "Server Version|Architecture"
#   Server Version: 29.4.0   OSType: linux   Architecture: aarch64
docker run --rm --platform linux/arm/v7 alpine:3.19 uname -m   # → armv7l（arm/v7 原生可跑，非模拟报错）
```

### A3. ★ 最快可用命令（已实测，产物全部过验收）
```sh
cp tools/jit_worker/libJit.c /tmp/jitbuild/
docker run --rm --platform linux/arm/v7 -v /tmp/jitbuild:/w alpine:3.19 sh -c \
  'apk add --no-cache gcc musl-dev binutils >/dev/null 2>&1;
   cd /w && gcc -march=armv7-a -mthumb -mfpu=vfpv3-d16 -mfloat-abi=softfp \
     -O2 -fPIC -shared -nostdlib -Wall \
     -Wl,-soname,libJit.so -Wl,--hash-style=gnu -Wl,--eh-frame-hdr \
     -o libJit.so libJit.c'
# 容器内自检（同一次运行里跑）：
#   LINK_OK
#   readelf -h: Class ELF32 / Type DYN (Shared object) / Machine ARM
#   gcc (Alpine 13.2.1) / GNU ld 2.41
```
本机验收（输出摘录）：
```
$ file /tmp/jitbuild/libJit.so
ELF 32-bit LSB shared object, ARM, EABI5 version 1 (SYSV), static-pie linked, not stripped
$ python3 tools/jiritsu_pack.py --check-so /tmp/jitbuild/libJit.so ; echo $?
0
```
未定义符号（容器内 `nm -D libJit.so`）：
```
U fclose  U fgetc  U fopen  U fputs*  U fwrite  U snprintf  U strcmp  U system
```
*musl 的 stdio.h 把 `fputs` 内联成 `fwrite` 调用，所以有的构建只出 `fwrite`。
两个符号 glibc（相机侧）都有 ⇒ 无 ABI 风险。全程 `-nostdlib`，产物只引用 POSIX 符号，
符合"相机用户态是 glibc/ARM32"的要求（musl 只当编译宿主，不进产物）。

### A4. 顺带：现有 `libJit.o`（本机 Apple clang 编的 ELF 可重定位对象）也能用容器 ld 直接链
```sh
docker run --rm --platform linux/arm/v7 -v /tmp/jitbuild:/w alpine:3.19 sh -c \
  'apk add --no-cache gcc musl-dev binutils >/dev/null 2>&1;
   cd /w && gcc -march=armv7-a -mthumb -mfloat-abi=softfp -shared -nostdlib \
     -Wl,-soname,libJit.so -o libJit_from_o.so libJit.o'
# readelf: ELF32 DYN ARM, Flags 0x5000200 Version5 EABI soft-float；4 个导出全在
```
⇒ Makefile 可以改成两步：本机 clang 只编 .o（现有 CFLAGS 去掉 -shared），容器做链接。
或干脆整段进容器（A3 一条命令更省事）。arm/v7 容器在 OrbStack(arm64) 上跑得飞快，5.8 KB 产物秒出。

### A5. 备选（未动用）
brew 装 `lld`/`binutils` 也能解决（`brew install lld` 后有 `arm64`... 实际要 `ld.mold`/`ld.lld` ELF 模式），
但 brew 编译要等；OrbStack 已在跑，故容器路线最快。

---

## B. QEMU（refs/zve10-qemu）本机可行性 —— 只读调查结论

### B1. fork 还是补丁集：是"补丁集"，但基座是私有 fork
```
refs/zve10-qemu/patches/qemu/{bionz.patch, sd-cid.patch}
refs/zve10-qemu/patches/kernel/{kconfig-pcie-qemu.patch, tty-visible-qemu.patch, adrs_conv_qemu.c ...}
refs/zve10-qemu/patches/qemu-cxd90045-vip-display.patch   (2 个 diff)
```
- 没有内嵌 QEMU 源码树；`bionz.patch` 修改的是**已存在的 `hw/arm/bionz.c`**（diff 有 index 行、无 new file mode）
  ⇒ 基座是他们的 fork `<build>/src/qemu-sony`（见 docs/HANDOFF_2026.md:76）。
- 基线版本：`docs/QEMU_BOOT_PROGRESS.md:17531`
  `qemu-sony/arm-softmmu/qemu-system-arm（5.1, cxd90045+GTK）` ⇒ **QEMU 5.1 fork**，机器名 `-M cxd90045`（scripts/ 多处）。
- ★ 关键坑：**qemu-sony 源码树（含 bionz.c 全部 ~1000 行机器模型）不在公开 repo 里**。
  本地 clone 的 origin = https://github.com/cokeenet/zve10-qemu，GitHub API 列目录确认与本地一致
  （没有 qemu 源码、没有 Dockerfile：`find refs/zve10-qemu -iname "Dockerfile*"` → 空）。
  公开增量补丁缺了基座 bionz.c 就合不回去 ⇒ **必须向 zve10 团队索取 qemu-sony 树（或其 tarball）**。

### B2. 他们的起法（scripts/run_qemu_zve10.sh 关键行）
```sh
: "${QEMU:=/usr/local/bin/qemu-system-arm}"
exec "$QEMU" -M cxd90045 -display none -serial stdio \
  -kernel "$ZIMAGE" -initrd "$INITRD" \
  -drive if=mtd,file="$EMMC",format=raw \
  -device loader,file="$BACKUP",addr=0x02E80000,force-raw=on \
  -append "earlyprintk $(cat "$CMDLINE_FILE")"
```
输入 5 件：ZIMAGE(打补丁内核) / EMMC 全盘镜像 / INITRD / BACKUP.BIN.fixed / cmdline.txt。
没有 Docker/容器化说明；`docs/HANDOFF_2026.md:13` 用 `<build>/qemu-build/arm-softmmu/qemu-system-arm`
（QEMU 5.1 旧式 configure 目录布局）；`<build>/src/a7c-kernel/linux` = 他们手里有 **A7C 内核源码**（也不在 repo）。

### B3. 本机 qemu 现状
```
which qemu-system-arm qemu-system-aarch64 qemu-arm  → 全没有；brew 也没装 qemu
```

### B4. 可行性判断与最短路径（推荐）
macOS 原生编 QEMU 5.1（旧 configure、无 meson）在 arm64/macOS 上坑多，**不推荐**。推荐：
```sh
# OrbStack 里 arm64 Linux 容器编他们的 qemu-system-arm（TCG arm64→arm32，全系统模拟）
docker run -it --rm -v $PWD/work/qemu-sony:/src arm64v8/ubuntu:22.04 \
  bash -c 'apt-get update && apt-get install -y build-essential pkg-config libglib2.0-dev \
    libpixman-1-dev libslirp-dev python3 && cd /src && \
    ./configure --target-list=arm-softmmu --disable-vnc --disable-sdl && make -j$(nproc)'
```
（QEMU 5.1 是 configure+make，正合旧树；arm-softmmu 在 arm64 host 上交叉编目标没问题。）
最大障碍（按序）：
1. **拿不到 qemu-sony 基座源码**（bionz.c/cxd90045 机器模型没公开）——这是硬依赖，先要向 cokeenet 团队要；
   自行按 QEMU_BOOT_PROGRESS 重写机器模型 = 周级工作量。
2. **打补丁的 A7C zImage**：包里没有内核源码；他们 `<build>/src/a7c-kernel/linux` 有现成的（含 CONFIG_CXD900X0_QEMU 等），同样要到人手里。
3. 显示链路未模拟完（README C 表 6 ❌）——跑到"能下命令的 shell"（`scripts/shell_camera.sh` 路线）现实，跑 UI 还早。
性能不是问题：他们 guest 跑到 70.6s / 33 模块加载，TCG 在 Apple Silicon 上只会更快。

### B5. 事实核对：A7C 更新包里有什么、QEMU 缺什么（实测）
包内（`firmware.tar_unpacked/`）：
```
0700_part_image/dev/nflasha3  FAT：vmlinux.bin(4.1MB, 裸内核) + initrd.img(2.1MB) + sabin/ssboot.bin …
0700_part_image/dev/nflasha5  WBI1 头（warm boot image）
0700_part_image/dev/nflasha7  ext2 rootfs（busybox）
0700_part_image/dev/nflasha15 ext2 /usr（App/kmod，含 backup.ko 等待打补丁的 kmod）
0300_partconf/partinf.conf    全盘分区表（nflasha1..23 起始/大小，可直接合成整盘镜像）
0800_appli/setting/kemco.txt  ★ 出厂内核 cmdline（含 mem=1G@0 / mem=256M@0x80000000@1 / root=/dev/ram0 initrd=0x700000,8M …）
0800_appli/tmp/               nflasha10(/tmp=/etc) 出厂种子
0110_backup/SYSASTRA-DSLR/NB{,_HIBIKI2}/CH886xx_*.bin  各 1,210,408B —— 是语言/地区固件数据，
                ★ 不是 BACKUP.BIN！(真机 /setting/Backup.bin=1,235,836B，在 nflasha2，运行态校准数据)
```
对照 zve10 侧证据：`docs/QEMU_BOOT_PROGRESS.md:2013/2017`
「backup.ko 的 init 要 `filp_open("/setting/Backup.bin")` … Backup.bin 在 nflasha2 里有（1,235,836 B）」；
`data/partition_map.tsv` 里 nflasha2/6/10/11/12 在包里**没有镜像**（空列）。

结论（四件套 + initrd/cmdline 逐项）：
| QEMU 输入 | A7C 包能否提供 | 说明 |
|---|---|---|
| 全盘 eMMC 镜像 | **可合成（近似）** | partinf.conf + nflasha3/5/7/15 + 0800_appli/setting,/tmp,/lens(0800_appli/lens) + 0650_prfile/PMBP 按偏移拼 1888MiB；空 vfat 造 nflasha6/10/11/12/13。缺真机数据区（见下行） |
| `/setting/kemco.txt` 真机 cmdline | **包里有出厂版**（0800_appli/setting/kemco.txt）| 与 zve10 真机 mem 布局完全一致（他们的 bionz patch 就是对齐这组值）；一般够用，除非用户改过 |
| BACKUP.BIN(.fixed) | **必须真机 dump** | 在 nflasha2(/setting)，逐机校准数据；包里的 0110_backup 不是它。dump 后还要按 HANDOFF 做 BIN/BAK 键修补 + A7C 版 backup.ko 惰性初始化手术 |
| 打补丁内核 zImage | **包里没有** | 包只有二进制 vmlinux.bin（不可 patch 到他们的 5 项内核修改）；需要内核源码 → 在 zve10 团队 `<build>/src/a7c-kernel/linux` 手里 |
| initrd | **包里有**（nflasha3/initrd.img） | 他们脚本说"自己从设备导出"，其实更新包即是来源 |
不拆机能凑出的：整盘近似镜像 + cmdline + initrd + rootfs/usr 全部内容。
必须真机 dump 的：①`/setting`(nflasha2) 全分区（Backup.bin + 校准/psd.bin + 序列号）②nflasha12(/cert)
③（可选）nflasha11 /log 现状；必须向 zve10 团队要的：④qemu-sony(5.1+bionz) 源码 ⑤打过补丁的 A7C 内核源码/zImage。

---

## 汇报（三句话版）
1. **libJit.so 已链接成功**：OrbStack 的 `--platform linux/arm/v7 alpine:3.19`（gcc 13.2.1/ld 2.41）一条命令出件；`file`=ELF32 LSB shared object ARM EABI5、`jiritsu_pack.py --check-so` 返回 0、未定义符号只有 fopen/fclose/fgetc/fputs/fwrite/snprintf/strcmp/system（全在 glibc）。产物在 `/tmp/jitbuild/libJit.so`（未写入项目目录）。
2. **QEMU**：本机无 qemu、无 ELF 工具链；QEMU 5.1 的 `qemu-sony` fork 源码不在公开 repo（只有增量补丁）⇒ 最短路径 = 向 cokeenet 要 qemu-sony 树 + a7c-kernel 源码，在 OrbStack arm64 容器里 `configure --target-list=arm-softmmu` 编译，再 `-M cxd90045` 跑；最大障碍是拿源码，不是性能。
3. **A7C 包凑 QEMU 输入**：cmdline(kemco.txt)/initrd/整盘(合成)都有；**缺 Backup.bin（真机 nflasha2 dump）和打补丁内核（源码在人手里）**；`0110_backup/` 里的 CH/CX .bin 是语言固件数据，不是 BACKUP.BIN。

---

## worker 链接与自测实测结果（2.00 libJit.so，tools/jit_worker）

1. **链接**（`make docker`，OrbStack `--platform linux/arm/v7` alpine:3.19，原生 arm/v7）
   - `file libJit.so` → `ELF 32-bit LSB shared object, ARM, EABI5 version 1 (SYSV), static-pie linked, BuildID[...], not stripped`
   - `nm -D` 未定义符号只有：`fclose fgetc fopen fputs fwrite snprintf strcmp system`（8 个，全在 glibc；`unlink` 声明了但没用到，被编译器删掉）
   - 产物直接落在 `tools/jit_worker/libJit.so`（不再是 /tmp）
2. **验收**：`python3 tools/jiritsu_pack.py --check-so tools/jit_worker/libJit.so` → **exit 0**
3. **自测**（`make test`，同一 arm32 容器 `gcc -O1 selftest.c -ldl` + `./selftest ./libJit.so`）：
   `CreateScriptI -> obj=0x19700101`、`LoadScriptI(...) = 1`、`RunScriptI(...) = 0`、
   `WORKER.VER 存在? 是`、`WORKER.NAME 存在? 是`、`cmd.ran 存在? 是`、`WORKER.DONE 存在? 是`、`PASS`；
   `/tmp/jiritsu/cmd.log` = `hello-from-worker`（说明 cmd.txt 里的命令经 system() 真执行）。
   注意：`system()` 在 musl 容器里正常；相机上是 glibc，行为一致（fork+/bin/sh -c）。OrbStack 挂载写回的
   文件属主映射成宿主用户，`make clean` 不受 root 属主影响。
4. **ABI 属性对比**（`make attr`，容器里 `readelf -A`）：两者
   `Tag_CPU_name "7-A" / Tag_CPU_arch v7 / Tag_CPU_arch_profile Application / Tag_THUMB_ISA_USE Thumb-2 / Tag_FP_arch VFPv3-D16`
   完全一致；**两边都没有 `Tag_ABI_VFP_args`（也没有 `Tag_ABI_PCS_float` 这个标签）**，即都是 base AAPCS / softfp
   （float 走核心寄存器），ELF Flags：我们 `0x5000200`（Version5 EABI + EF_ARM_SOFT_FLOAT），相机库
   `0x5000002`（Version5 EABI + EF_ARM_HASEFMDOT），都**没有** `EF_ARM_VFP_FLOAT`（=硬浮点 ABI）⇒ FP ABI 兼容。
   差别只有相机库多 `Tag_ABI_HardFP_use: Deprecated` 与 `Tag_DIV_use: Not allowed`；我们的 .so 里没有 SDIV/UDIV
   也没有任何 VFP 指令（worker 不做算术），所以这两条差异无影响，不会与相机 glibc/ARMv7 环境不匹配。
5. **改动**：只动了 `tools/jit_worker/Makefile` —— apk 包列表补 `file`（原来 `file: not found`，看不到验收要求的
   file 行），并新增 `make attr` 目标做上面的属性对比。libJit.c / selftest.c 未改，一次通过。

## ★新（实测）：相机自己的用户态可以离线跑（arm32 容器 + 相机自带 ld.so/glibc）
之前只能"编 arm32"，现在能**直接执行相机自己的 ELF**：
- 相机 rootfs(nflasha7) 的 `busybox = v1.29.3 (2021-02-04)`，glibc = **2.11.2**（`libc-2.11.2.so`），interpreter `//lib/ld-linux.so.3`。
- 解 part_image 时 **所有符号链接都丢了**（`/bin/sh`、`/bin/tar`、`libX.so.N`），所以要现补软链再跑（旧笔记里"`/bin/sh` 不存在"就是解包假象；nflasha7 里是 mode `0xa1ff`、target `"busybox"` 的 fast-symlink）。
- 现成脚本：`tools/camuser.sh`（宿主侧）+ `tools/camprefix.sh`（容器内 source，定义 `BB`/`CAM`）。镜像 `debian:buster-slim`（glibc 的 arm/v7），**用相机自己的 `/c/lib/ld-2.11.2.so --library-path /c/lib` 跑它自己的 ELF**，M4 上原生 armv7，无需 QEMU。
  - 自检：`bash tools/camuser.sh` → 打印相机 busybox 版本。
  - 跑脚本：`bash tools/camuser.sh work/t_tarcheck.sh`（脚本里 `. /t/camprefix.sh`，然后 `BB tar …`）。
- 已用它得到的实测结论（详见 `FIRMWARE_MOD.md §3.1.1`）：
  1) `set_firm` 的载荷 tar **必须含 `./` 目录项**，否则相机固定命令 `tar xpf F ./ -C DIR` 返回 rc=1（"tar: .: not found in archive"）；`jiritsu_pack.py` 已修，现在 **rc=0 且解出的 libJit.so 字节一致**。
  2) busybox 会剔掉成员名里的 `../`（"removing leading './../../'"）⇒ **tar 成员不能越出解包目录**。
  3) 成员**不带 `./` 前缀**时，`xpf F ./ -C DIR` 什么都不解（rc=1，落地为空）⇒ 条目必须 `./` 开头（打包器已保证）。
- 顺带可得（未做，值得做）：用 `CAM /c/bin/…` 试跑 nflasha7 里的其它 ELF（`crypter.elf` 在 nflasha15，需要把两个分区的库合到一个 sysroot 才能跑）。
