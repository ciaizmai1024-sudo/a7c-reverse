# Round 14 (续跑) —— mode5 卡线 + 正向/负向验签对照

时间线：本轮为**续跑**（上一轮 12:42–13:50 的残留已在远端 `~/qemu-a7c/`，见 §0）。所有新产物带 `r14b`/`r14c` 前缀。

## 0. 上一轮残留（复用，不重做）
远端 `~/qemu-a7c/` 里已有：
- `run_r14.sh`（两阶段 wrapper，`inject_mode5.sh` 每轮往 a2 塞 `updater/mode5`）、`inject_mode5.sh`
- `r14/tree`（上一轮 initrd 解包树，含 `r14bin/loattach`、`r14bin/fsyswrap_r14.so`）
- `initrd_r14.img`（5,103,616 B）、`a7c_emmc_r14.img`（1,356,857,344 B）、`card_r14.img`（369,098,752 B，vfat）
- 日志 `r14_r14{r,s}_boot{1,2}.ser/out`（mode5 跑到 `[DETAIL] MODE=5` → `sdfileinput.elf` → `SDFileManager.cpp:45 "ret of Fsys_Mount() = 80000041"` → `[FIRMUP NG] Error 77`）
- `r14src/fsyswrap.c`（上一轮的 Fsys_Mount 拦截雏形，只把 mount 转到 `/mnt/fsysx`，没有实现 Fsys 语义 ⇒ 没往下走通）

## 1. 基线复验（本轮开始时实测，未改）
| 资产 | 期望 | 实测 |
|---|---|---|
| `qemu-sony/arm-softmmu/qemu-system-arm` | `e3ae292c…` | **`e3ae292c7bfeccd64dd8397bf976a5a7` 一致** |
| `qemu-sony/hw/arm/bionz.c` | `32dbbd76…` | **`32dbbd764eb86d2906e335e28d28231c` 一致** |
| `qemu-sony/hw/sd/sd.c` | `e13776d0…` | **`e13776d00063a02d3adbd2aef74e89a5` 一致** |
| `a7c_emmc_pt4.img`（基线盘） | `85876746…` | **`8587674613a0ffd86beea010e74fd47c` 一致，未动** |
| `a7c_emmc_r13.img` / `_m5.img` | `c84208c9`/`d526e5f0` | 一致 |
| `ksrc-r13/arch/arm/boot/vmlinux.bin` | `5ad80118…` | **漂移**：现 `7a5399b5393ecb85a20dd7fef624f990`（内核在上一轮 13:31 被重建，`#13 SMP PREEMPT RT`；带 ftrace 的变体另存为 `vmlinux_r14_ftrace.bin` = `aa81b6d5…`；`vmlinux_r12.bin` = `84c21ba3…`）。源码级 diff `ksrc-r12` vs `ksrc-r13` 只有 `arch/arm/mach-cxd900x0/{Kconfig,include/mach/system.h}` 两处（= Round 13 已知的去 `!CXD900X0_QEMU` + reboot 补丁），**没有新的源码改动** ⇒ 属"同配置重建/配置漂移"，非本轮偷偷改。 |

## 2. 已确证（本轮实测/复核）
- **卡片的宿主落点**：eMMC 镜像 USER 分区表（host offset `0x400000`）里 **表 index 10 = 500 MiB vfat**（`0xb800000`，host `0xc000000`）；guest 里它叫 **`/dev/nflasha11`**（guest 命名比表 index 大 1）。上一轮的 `card_r14.img`（369 MB vfat，含 `BODYDATA.DAT` 346,206,712 B）就是写在这块 ⇒ **卡片=一个真 vfat 分区，用 loop 挂出来**（guest 里 `loattach /dev/loop0 /dev/nflasha11` + `mount -t vfat /dev/mmca1 /ramdsk/mnt` RC=0，`ls` 见 346 MB 文件）。
- **卡片读得到的程度**：**没有 SD host**（CXD900x0 PCIe-DME + mcmn SD 控制器 QEMU 里没有模型）。`sdfileinput.elf` 的 `SDFileManager::Initialize`（`libsdfileinputupdaterapi.so`，vaddr `0xd904`）依次 `mcmn_init@plt 0xb0e8` → `Fsys_Init@plt 0xaf74` → `Fsys_Mount@plt 0xd944`，`Fsys_Mount` 返回 **`0x80000041`**（= 没有卡/设备），随后 `[FIRMUP NG] Error 77`。内核侧同期打：`[MMC_OS] slot0 Bus type = 1` / `MMC:Failed mcmnd_api_getbkupinfo_bus_connect_type` / `Force Local bus` / `[MMC_DRIVER] Slot 0 is PCI Bus` / `<d9::0>[MCMND][BKUP][ERR] line = 4605, ret = 80000001`。
- **官方明文流的尾部不是签名**（本轮新事实，秒级实测）：`work/v203/full_dec_200.bin`（344,853,504 B）**最后一个非零字节在 `0x148e072c`**（距 EOF 1235 B），**末 256 B 全零**；`RSA_verify(SHA256(stream[:-256]), stream[-256:])` 用官方 `/etc/VerificationKey.pem`（RSA-2048，modulus `c0603c10…`）**失败**（padding check failed）。
  ⇒ **"未改一字的官方 2.00 明文流"按其自己的 `verify_info{data=buf,len=total-0x100,sig=buf+total-0x100}` 布局不会自带合法签名**（真机卡上的 BODYDATA.DAT 尾部 256 B 我们**没有 dump**）。⇒ 正/负对照只能**自签**（见偏离清单）。

## 3. 本轮做法（mode5 走到底的最小路径）
不做 PCIe-DME/mcmn SD host 全模型（时间不够），改为在 **Sony Fsys 用户态 API 边界**打 LD_PRELOAD 桩：
- 需要实现的 import（精确集合，`nm -D --undefined-only` 实测）：
  - `libsdfileinputupdaterapi.so`：`Fsys_Init Fsys_Exit Fsys_Mount Fsys_Unmount Fsys_FindFirst Fsys_FindNext`(+ `mcmn_init`)
  - `libupdatercommon.so`（`Updater::FsysFileHandler` 的实现处，vaddr `0x657c` C1/`0x659c` Open/`0x65dc` Close/`0x66a4` Read/`0x672c`,`0x67bc`,`0x67ca` Seek/`0x661c` Write）：`Fsys_Open Fsys_Close Fsys_Read Fsys_Write Fsys_Seek`
- 从反汇编读到的语义（E1）：handler 对象布局 `[0]=vptr, [4]=Fsys handle(int), [8]=opened flag`；`Open(path,mode)` ⇒ `Fsys_Open(path, &this[4], mode)`，返回 0=成功，handler `Open()` 返回 **1**=成功/**0**=失败（失败打 `0x3001a`/`"D"` 日志）；`Close()` ⇒ `Fsys_Close(this[4])`，0=成功；**handle 必须非 0**（`cbnz r0` 判定 ⇒ 0 = "未打开"）；`Read(this,buf,len)` ⇒ `Fsys_Read(handle,buf,len)`，返回值参与 `>=0` 比较 ⇒ 按"读到的字节数(≥0)/负=错"实现；`Seek(long)` ⇒ tail-call `Fsys_Seek(handle, off, 0)` ⇒ 3 参 (handle, off, whence)。
- 桩把这些 Fsys_* 映射到 guest 里已挂好的 vfat 目录（`/ramdsk/mnt/BODYDATA.DAT`）的 POSIX open/read/lseek；**卡内容仍按块读**（handler Read → 我们的 read(fd,…)），只是传输/枚举/FAT 解析全部换掉（进偏离清单）。

## 4. 本轮新产物 + run r14b0（mode5 + Fsys 桩，机制性一次）
新增（远端 `~/qemu-a7c/`，副本在 `results_round14/` 与本目录）：
| 文件 | md5 |
|---|---|
| `r14src/r14fshim.c`（Fsys 桩源码） | 见本地同名文件 |
| `r14/tree/r14bin/r14fshim_r14b.so` | `7575745c8ac8c0e4d285d39ad943285d` |
| `r14/tree/usr/bin/insmod.sh`（卡片挂载改为常驻，不再 umount） | `e2719722d662619ad540a50d16bdd56b` |
| `r14/tree/usr/bin/execute_ufp.sh`（mode5 分支加 `LD_PRELOAD=…/r14fshim_r14b.so` + 先挂卡） | `d72ab6971501f3ffe4e107a4b2d75818` |
| `initrd_r14b.img`（`mkfs.cramfs r14/tree`，5,111,808 B） | `a0a0883f1aa69fb520971c1d76d161c8` |
| `a7c_emmc_r14b.img`（= r14 盘副本，卡片=vfat 在表 index10 / host `0xc000000`） | `a2269a6e566a8d884a2516779e0ccda8` |
日志：`r14_r14b0_boot1.ser`（10,418 B，截在 `eMMC: 1290MiB …`）/ `r14_r14b0_boot1.out`（RC=124 timeout）。

**结果：run r14b0 在 `insmod.sh` 打到任何 `R13-*`/`R14-*` 标记之前就断流**，Fsys 桩没有被调用（`R14FSHIM` 0 条），**正/负验签对照本轮未拿到**。
断流点与上一轮被中断前最后三次 run（`r14_r15b/r14_r16a`，ser 都是 10,417/10,418 B，同样截在 eMMC 识别处）**完全一致** ⇒ 不是我这次补丁引入。
可复现的区分事实：
- 12:57 的 `r14_r14s`（ser 1.1 MB，能看到 `[DETAIL] MODE=5` + `Fsys_Mount 80000041` + `Error 77` + 完整 R14-CARDSETUP）用的是 **13:31 重建之前的 ksrc-r13 内核**（当时 md5 `5ad80118…`）。
- 13:31 之后的内核 `vmlinux.bin` = `7a5399b5…`（本轮 r14b0 也用它）⇒ 之后所有 run 全部断流。注意 `ksrc-r13/usr/initramfs_data.o` 在 13:31 也被重建（**内核内建 initramfs**，3.0 内核里内建 + `-initrd` 会先后解包两次），这是最可疑的断流原因（**未证实**）。
- 下一步（已备好，不需再分析）：同一 `initrd_r14b.img` 换内核再跑一次即可定位：`vmlinux_r12.bin`=`84c21ba3…`（ksrc-r12，Round 12 内核）或恢复 `5ad80118` 内核；若换内核后能出 `R14FSHIM Mount`，正/负对照就只差两步：
  1) `openssl genrsa` 自签（`fdat_r14pack.py CARD里的BODYDATA.DAT full_dec_200.bin OUT --sign priv`，`--flip <body中段偏移>` 出负样本），
  2) 把自签公钥替换进 initrd `etc/VerificationKey.pem`（现仍是官方键 `ecbe36e0…`）。
  `full_dec_200.bin` 已 rsync 到远端 `~/qemu-a7c/r14src/`。

## 5. 偏离清单（本轮，全部不代表真机行为）
1. **卡传输层=假**：没有 CXD900x0 PCIe-DME / mcmn SD host 模型；卡是 eMMC 里表 index10（host `0xc000000`，500 MiB）的 vfat，guest 里 `loattach /dev/loop0 /dev/nflasha11` + `bind` 到 `/dev/mmca{,1,aa1}`（Round 14 上一半的做法，本轮沿用）。
2. **Fsys 层=桩**：`r14fshim_r14b.so` 用 POSIX 顶掉 `Fsys_Init/Mount/Unmount/Exit/Open/Close/Read/Write/Seek/Seek64/FindFirst/FindNext/GetFileSize` 与 `mcmn_init`（返回值一律 0=成功；`mcmn_init` 的 0 是**伪造**）。Sony 自己的 FAT 解析/簇链完全没走。
3. **`Fsys_FindFirst` 的结构体布局未知**（按"前 260 B 放文件名"猜），`Fsys_Seek64` 是猜测的变体；这三处若真机语义不同会假阳/假阴（本轮未跑到，无实测）。
4. **签名/密钥=自签**（计划内）：官方明文流末 256 B 全零 ⇒ 正对照必须换成我们自己的 RSA-2048 键 + 我们把签名放到流尾；这检验的是"相机自己的 VerifySignature 代码对 1 字节翻转的判定"，不是 Sony 的签名链。真机卡上 `BODYDATA.DAT` 尾 256 B 仍缺 dump（见 `work/BACKUP_MANIFEST.tsv` 的 BODYDATA.DAT 行）。
5. 内核 md5 漂移（`7a5399b5`，源码未变）：见 §1，属上一轮的重建，本轮未修。

## 6. 复核修正 / 下一轮起手（写死，免得再猜）
- "内核内建 initramfs" 猜测**被否**：`ksrc-r13/.config` 与 `ksrc-r12/.config` 都是 `CONFIG_INITRAMFS_SOURCE=""`（`usr/initramfs_data.cpio` 只有 512 B 空壳）。两个内核的真实差别只剩 `.config`（13:31 那次重建带/不带 ftrace 之类）与编译时间。
- 因此 r14b0 断流最可能仍是**用户态崩在 insmod/UdtrMain 早段 + Exception monitor 冻住 amba2 控制台**（Round 13 已知行为）。下一轮顺序：
  1) `IMG=a7c_emmc_r14b.img ./run_r14.sh r14c1 initrd_r14b.img vmlinux_r12.bin 120 150 parts/backup_ram_r13.bin`（换 Round 12 内核 `84c21ba3…`，其余不变）→ 若出 `R14FSHIM Mount` 即机制通；
  2) 若仍断流：把 `r14/tree/usr/bin/insmod.sh` 里 R14-TRACE/R14-CARDSETUP 两段挪到 `insmod` 全部之后（上一轮已知 R13 序列能跑完，见 `r13_r14q_boot1.ser`），二分定位；
  3) 机制通后：`openssl genrsa -out r14src/r14c_priv.pem 2048`；正样本 `python3 r14src/fdat_r14pack.py <现卡里的 BODYDATA.DAT> r14src/full_dec_200.bin /tmp/pos.BODYDATA.DAT --sign r14src/r14c_priv.pem`，负样本同上再加 `--flip 0x10000000`（**签名在翻转之前算**，脚本已是这个次序）；写进 vfat（`sudo mount -o loop,offset=0xc000000 a7c_emmc_r14b.img`）；`r14c_pub.pem` 换进 initrd `etc/VerificationKey.pem`。
  判据：正 = 无 `Signature Verification Error`；负 = 必须出现 `Signature Verification Error` + `ApiException 0x30002`。
- 远端已就位：`r14src/full_dec_200.bin`（344,853,504 B）、`r14src/fdat_r14pack.py`、`r14src/r14fshim.c`、`initrd_r14b.img`、`a7c_emmc_r14b.img`。
