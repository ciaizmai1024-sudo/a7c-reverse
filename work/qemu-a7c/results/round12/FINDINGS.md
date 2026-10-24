# Round 12 — 正经链跑通:backup.ko file_load **真成功** → mcmn_drv insmod → sauu 到达 WaitingConnectionState

## ① file_load 过没过 / 路线
**过了,走 (i) 数据侧**(但不是合成文件——是**真机 Backup.bin/.bak 原文件**),关键不在文件内容,而在 **模块参数 `Backup_load=1`**:

- 判据达成:`insmod backup.ko Backup_load=1 Backup_save=0 Backup_pri_file=... Backup_sec_file=...` → **RC=0**,串口**不再打** `backup_init() error (file_load)`;`grep -c Backup_ /proc/kallsyms` = **38**(含 `Backup_read`);后续 `osal_ulogio/dmm/i2c` 全部 insmod 成功(基线里它们全报 Unknown symbol)。
- 使用的文件 = 真机 a2 区 `/setting/Backup.bin`(md5 `7a549d06…`,cookie **0xaaaaaaaa**、`BK4`、count@0x2c=750(0x2ee))与 `Backup.bak` 的 byte-identical 拷贝(放 initrd `/r12/ctrl.bin|.bak`;r10b 已证 FS 无关,tmpfs/cramfs/vfat 一样)。

### 真正的根因(推翻 Round 11 的 cookie 结论)
反汇编原生 rescue ko(`work/v203/a1_initrd/usr/kmod/backup.ko`,md5 `0a38eec6…`,E1/逐条):
- **Round 11 的 `0x9000e1a0` 作废**：本地 `bk_dis.txt` 逐字看，原生 rescue ko(.text)里的 4 个 cookie 比较字面(0x52d8/0x5798/0x658c/0x7014)全是 **`0xaaaaaaaa`**——与真文件一致，cookie 从来不是门（`0x9000e1a0` 只存在于另一种 ko 变体，与本链无关）。
- 失败真身:`backup_init` 在 rel.init.text+0x144 **读 `Backup_load` 变量值**(.bss reloc @0x30c)并把该**整数值**当参数传给 `backupfile_load` → `backupfile_init(path, r9=Backup_load)`。
  - **`Backup_load != 1`**(USER 模式默认):走 653c 分支,`Data_init` 不吃重新加载的文件缓冲,而是吃 **`arch_phys_to_cache(u32@hdr+0x00)`** 映射出来的缓冲——真机文件 hdr+0x00=`0x02e80000`(=产品运行时把 backup 镜像放进 RAM 的物理地址;bootargs `memrsv=0x75e000@0x02E68000` 正覆盖该区域)。在 updater/QEMU 里该映射是垃圾/失败 → `Data_init` 的 `strcmp(hdr+12,"BK4")` 必败 → EIO。**这解释了为什么改 cookie、换文件、挪文件系统全都无效**(内容根本不看)。
  - **`Backup_load == 1`**(官方 initrd 恢复分支 `insmod.sh:30` 本来就这么传,配合 `ud_get_serial_cfg_file.elf`):651c 分支 → `backupfile_load_file` 按 stat 全尺寸重读文件 → `Data_init` 校验真缓冲:`strcmp(hdr+12,"BK4")==0` ✓、cookie==0xaaaaaaaa ✓ → 成功。
- 推论(E2,待真机印证):**真机 USER 模式(不带 Backup_load)大概率同样打 `error (file_load)`**——同一 ko、同一 hdr+0、同一 memrsv(pa_uc 机制在 QEMU 已镜像)。真机恢复/产线流程用 `Backup_load=1`(文件来自 serial-cfg RAM blob @0x02e68000 区)才会让 backup 数据层活过来。

## ② `Data_init`/链路的字段级要求(原生 rescue ko,E1 置信度除非注明)
文件加载链(`backupfile_load`@0x6684 → `backupfile_select_path`@0x5e38 → `load_file`@0x5fec → `Data_check`@0x54e4 → `backupfile_init+0x1a0`@0x65a4 → `backupfile_init`@0x6404 → `Data_init`@0x4664):
| 偏移 | 字段 | 要求 | 备注 |
|---|---|---|---|
| hdr+0x00 u32 | 产品 RAM 物理地址(legacy) | `Backup_load=1` 时**不参与校验**;=0 时必须是合法可缓存 pa(DDR0 [0,pa_uc[0] 或 DDR1)否则 `arch_phys_to_cache`→0→失败 | 真值 0x02e80000 |
| hdr+0x04 u32 | cookie | 与真文件同值 **0xaaaaaaaa**（比较字面 @0x52d8/0x5798/0x658c/0x7014；pri==sec 时成对校验） | E2：只从实验可推（真文件过，改过的不过）|
| hdr+0x08 u32 | write-comp | 仅当 `Data_check` 第三参≠0 时要求 ==1;load 路径传 0,不检查 | 真值 1 |
| hdr+0x0c char[4] | 格式版本串 | `strcmp` == **"BK4"**(`.rodata.str1.1+0x977`;BK3→hdr_size 256、BK2→32 是 `Data_GetHeaderSize` 的事) | GetFormatRevision:BK4→4,BK3→3,BK2→2 |
| hdr+0x10 u32 | 记录数(表) | `Data_init` 存 `table=[buf+0x100, buf+0x100+6*N]`,无越界校验 | 真值 750 |
| hdr+0x2c u32 | `Data_GetCount` | pri/sec 之差只决定 Data_check 先查哪边cookie;返回 1/2 即过 | 真值 750/750(相等→走 sec 侧 cookie 检查,过) |
| hdr+0x38 u32 | checksum | 只在 save/sync 路径用(`Data_CalChecksum`=**字节和,非 CRC**,sum-1,cmn 3 界) | load 不算 |
| hdr+0x20/0x14/0x18/0x1c/0x24/0x28/0x3c | ID1/其它 | load 路径不校验(只在 dump 例程 0x41c0 打印) | |
| 文件大小 | ≥0x100(头部阶段按 0x100 读;`Backup_load=1` 再按 stat 全量读并读满) | 真值 0x127828 | |
| select_path | 参数串 ≤63 字符;会构造 `<去扩展名>.bak` 先查存在性,原路径兜底 | /r12/ctrl.bin+.bak 满足 | |
- `backup.ko` 无软失败不变(表 NULL → 后续调用崩);`Backup_save=0` 让 senser 软路径打印 `** NO SAVE MODE **`。

## ③ mcmn_drv.ko
- **insmod RC=0**,`/proc/modules`: `mcmn_drv 124978 0 Live`,`/proc/devices` mcmn=**249**,与 initrd 真节点 `/dev/mcmn (c 249,1)` 匹配。
- `backup` 模块被 mcmn_drv/i2c/dmm/osal_ulogio 4 方引用仍 Live。
- mmap 探针(`t_mcmn`,静态 arm 交叉编译):open **/dev/mcmn OK(fd=3)**,mmap(4K, RW, SHARED, off0)= **MAP_FAILED errno=38(ENOSYS)** —— 驱动该 minor 的 fops 不实现通用 mmap(sauu 内部用 libInfraMediaCommon 的 mcmn 接口,本轮它**不再 0xffffffff 崩**,说明其取表路径已通)。判据"无 unresolved symbol ✓、/proc/modules ✓、open ✓、mmap 直探针 ENOSYS(存疑:可能要求特定 offset/minor)"。
- `mmc_drv.ko` 仍失败:`Unknown symbol pcie_slot_ctrl/pcie_root_ctrl` —— 内核 `CONFIG_CXD900X0_PCIE2_DME` 未开(`mach-cxd900x0/pcie.c` 没编进 vmlinux)。D 线(卡/存储)先要开这个 config 重编内核。

## ④ sauu 走到哪
init 链:Power IC type 读到 **7 = DARWIN**(基线里 Backup_read 失败时读不出来)→ `us_darwin_init.sh`(镜头/PIC 串口链握手,`ud_darwin_init.elf` CRC 死循环——QEMU 无对端;**本轮把 us_darwin_init.sh 后台化+20s kill,偏离**)→ `UdtrMain.sh`→`execute_ufp.sh` USER 分支 → **sauu**:
```
UdrMAIN ... "Begin main()"
UpdaterInterface::Initialize OK; usbif_initialize OK; usbif_hndl::open OK
onEvent(CONNECTION) connection.val=0 (port 0)
UdrMAIN,0,UpdaterModeState.cpp:61,"BeginningState -> WaitingConnectionState"
```
**mcmn_log_init 崩溃消失**(mcmn_drv 装载即愈)。**到 WaitingConnectionState 为止:下一步需要 PC 侧 USB**(QEMU cxd90045 无 USB device/gadget 模型;`usbif` 靠 osal_utm/osal_uipc 轮询,val=0)。离线到头 = WaitingConnectionState;真机上此后由 PC(Sony 更新工具)经 USB 推 `WaitingCommunicationState → CommunicatingState → …`。

## ⑤ in-guest reboot
**QEMU 侧已做**:`bionz.c` 新增 4KiB MMIO `0xf240f000` "cxd90045-reset-hook":任何 4 字节写 → `error_report("R12-RESET-HOOK …")` + `qemu_system_reset_request()`;配 `-no-reboot` → QEMU 以 0x11 退出,外部 wrapper 再拉(同一持久 eMMC 镜像)。**新 md5:bionz.c `139a86cb…`(基线 87febf2b 备份为 `hw/arm/bionz.c.r11.bak`);新二进制 `arm-softmmu/qemu-system-arm` md5 `35b2e30c…`(旧 r12 备份 `.r12`)**。用 r12e initrd + `-no-reboot` 在新二进制上回归跑过(R12 结果逐项复现,无破坏)。
**guest 侧触发未闭环**:基线内核 `arch_reset()` 是空 → busybox `reboot` 仍无写。内核 patch 已写好(`arch/arm/mach-cxd900x0/include/mach/system.h`:`arch_reset` 里 `writel(0x52E57001, 0xf240f004)`),但 ksrc-v3(3.0.27-rt106)在这台机上只有 gcc-9/gcc-13 arm 交叉器,**原 Sony 工具链 `arm-sony-linux-gnueabi-dev-gcc` 不在本机**;gcc-9 重建在 `kernel/exit.o` 等 BUILD_BUG `.err` 处断,未成功 → **重启闭环差一颗能编 3.0.27 的编译器**(补丁在 `~/qemu-a7c/ksrc-r12/`,已备份整树副本)。

## ⑥ 偏离清单(不代表真机行为)
1. **USER 模式 insmod 传了恢复分支才有的 `Backup_load=1`**(参数本身是官方语义,但真机 USER 链不传;等价于"把文件当 serial-cfg 文件喂"——真机对应是 `ud_get_serial_cfg_file.elf 6` 从 RAM blob 拷文件这条路径)。
2. initrd 内 `/r12/ctrl.bin|.bak` 是真文件拷贝(cramfs),非 /setting vfat(r10b 已证 FS 无关);另 `e1/e2/e3`(hdr+00 改 4/0x3fffffe0/0x80001000)、`v1..v6`(256/262B 合成文件)只用于判定"内容无关",**不是**可用备份。
3. `us_darwin_init.sh` 后台化 + `kill -9`(含 pkill ud_darwin_init.elf)——跳过 PIC/镜头链握手才到 sauu(真机这步会成功)。
4. insmod mcmn_drv 提前到 insmod.sh(USER 链本是 execute_ufp 的 insmodMediaDriver 在 MSCRYPT 里做);t_mcmn 是本轮自编探针。
5. QEMU 的 reset-hook 写地址 0xf240f000 是**合成的**,非真 PMIC/WDT 寄存器;bionz.c/二进制作废基线 md5(见⑤,旧源码备份 `.r11.bak`,旧二进制备份 `qemu-system-arm.r12`;从备份源码重建的二进制与基线二进制 md5 **逐字节一致** `d4103e35…`)。
6. 脚本微调:`r11/run_r11.sh` 输出名 r11_* → r12_*(仅命名);新增 `r12/run_r12nb.sh`(带 -no-reboot)。
7. pt4 镜像 **未改**(md5 85876746… 复验一致);QEMU 二进制换 r12 版(基线可即时还原,见⑤)。

## 产物与日志(远端 `~/qemu-a7c/r12/` 与 `~/qemu-a7c/results_round12/`,本地 `work/qemu-a7c/results/round12/`)
- `r12_r12a.ser`(hdr+0 变体 4×EIO)、`r12_r12b.ser`(合成最小文件 6×EIO,证内容无关)、`r12_r12c.ser`(**首次全绿**:BK-LOAD RC=0、38 syms、mcmn RC=0、major249)、`r12_r12d.ser`(sauu → WaitingConnectionState)、`r12_r12d.ser`(sauu → WaitingConnectionState)、`r12nb_r12e.ser`(t_mcmn open OK/mmap ENOSYS + WaitingConnectionState;此轮已用新 QEMU `-no-reboot`,r12e 只有这一份日志)。
- initrd:`initrd_r12a.img 0754f54a` / `r12c 08dfd982` / `r12d 38f80224` / `r12e 00cefd72`(全部 = 原 initrd loop-mount→cp -a→打补丁→mkfs.cramfs;kmod 内 backup.ko 保持原生 `0a38eec6`)。
- 探针:`t_mcmn.c`(自编,md5 8ea77410 in-guest)、补丁脚本 `bionz_patch.py`、`r12_setup2..5.py`;内核补丁树副本 `ksrc-r12`(未编成)。

## ⑦ 还缺什么(真机才能定)
1. 真机 USER 模式 insmod 原生 backup.ko:验证"USER 不带 Backup_load 也 file_load 失败"这一 E2 推断(=H2 的另一半),以及真机是否只在恢复/服务流程带 Backup_load=1。
2. 真机 serial-cfg blob(0x02e68000..0x02fc5fff 区)dump:喂给 QEMU 就能走 100% 原生恢复分支(`ud_get_serial_cfg_file.elf`),不再需要我们传参。
3. 能编 3.0.27 的 Sony 工具链 → 编 `ksrc-r12` → 重启闭环(guest `reboot` → QEMU 0x11 退出 → wrapper 重拉 → 第二次 boot 自证 a23 写入仍在)。
4. PC 侧 USB:QEMU 加 UDC/gadget 或 ud_* 注入才能离开 WaitingConnectionState;`mmc_drv`/卡更新线要开 `CONFIG_CXD900X0_PCIE2_DME`(同样卡工具链)。
5. mcmn mmap 语义(minor/offset)需在真机/带 PSOS 环境对照。
