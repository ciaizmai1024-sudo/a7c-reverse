# Round 15 —— mode5 真卡（官方 .dat）+ Fsys 桩修好；boot 截断根因＝那颗内核自己炸

时间：本轮超了 75 min 时间盒（约 110 min），产物一律带 `r15`。所有 run 都有串口日志。

## 0. 一句话结论
- **A（boot 截断）已修**：截断根因是 `vmlinux.bin=7a5399b5`（Round14 13:31 重编的那颗）**内核自己在 pid1/`swapper/0` 处跳到 0x00000000**
  → 进 in-kernel **Exception monitor** → amba2 控制台冻死 ⇒ 串口只剩 10,418 B。
  退回 `vmlinux_r12.bin`（`84c21ba3…`，ksrc-r12 树）后**完整开机**，串口出现 **`R15FSHIM Mount`**（Fsys_Mount 返回 0）、
  `SDFileManager::Initialize` 不再返 `0x80000041`、**没有 `Error 77`**。
- **B（真 .dat 上卡）已做**：卡 vfat 根目录放官方 `FirmwareData_ILCE7CV200.dat`（md5 `05862805…`，346,206,712 B）
  → **文件名 `BODYDATA.DAT`**（`sdfileinput.elf` 里的字面量），guest 里 updater 实际拼出的 Fsys 路径 = **`0:\BODYDATA.DAT`**（盘符 `0` + `\`）。
- **C（正/负验签）本轮没拿到**：mode5 链已经走到 **`SDUUDConditionChecker`（正在走 UFU 记录链）**，
  但卡在 chunk 走链 → **`[FIRMUP NG] : Error 42` / `verifyUUDCondition error`**，**还没到 `VerifySignature`**。
  最后一个 run（`p5`，修 `Fsys_Seek` 语义）在跑，见 §5。
- **D（写分区/重启重读/`MediaUpdateCompleteFlag`）未到**（被 C 挡住）。

## 1. A：boot 截断的定位与修法（判据＝串口出 `R15FSHIM Mount`）
隔离实验（同一 initrd/镜像只换内核，`run_r15.sh` 是 `run_r14.sh` 的参数化版本）：

| run | 内核 | initrd / 镜像 | 结果 |
|---|---|---|---|
| `r15_t1` | `vmlinux.bin` `7a5399b5…`（Round14 那颗） | `initrd_r13g.img` / `t_r15_t1.img`（Round13 已知能跑完整 mode5 的那一对） | **截断 14,826 B**；串口尾部：`program: (null)(swapper/0) (pid: 1) … vector exception (0x000) at 0x00000000` + `Entering exception monitor.` ⇒ **那颗内核在 init 早期自己跳飞到 0**，异常监视器吃掉控制台 |
| `r15_t2` | `vmlinux_r12.bin` `84c21ba3…` | `initrd_r14b.img` / `t_r15_t2.img` | **完整开机**：`R13-*`/`R14-*` 标记全出、`[DETAIL] MODE=5`、卡片挂载/`ls` 正常 ⇒ 内核是唯一变量 |

⇒ **Round15 起所有 mode5 实验都用 `vmlinux_r12.bin`（`84c21ba3…`）**。副作用：这颗没编 `CONFIG_CXD900X0_PCIE2_DME`
⇒ `insmod mmc_drv.ko` = `Unknown symbol pcie_slot_ctrl / pcie_root_ctrl`（`r15_p1` 实测），
所以把 `execute_ufp.sh` 的 `insmodMediaDriver()` 改成**失败不退出**（`R15-INSMOD-MMC-FAIL-IGNORED`）——偏离，见 §6。
注：`mcmn_drv.ko` 在 r12 内核下 insmod **RC=0**（`/proc/modules` 里在），只有 `mmc_drv.ko` 缺符号。

## 2. 上一轮"桩没生效"的真正原因（本轮第一个实质修正）
`r14fshim_r14b.so` 是**用宿主 gcc 编的**，带 `GLIBC_2.34` 版本依赖 ⇒ guest（glibc 2.11.2）里
`ld.so` 直接拒绝：串口 `sdfileinput.elf: /lib/libc.so.6: version 'GLIBC_2.34' not found (required by /r14bin/r14fshim_r14b.so)`，
`sdfileinput` 连 main 都没进（RC=1）。
⇒ 本轮重写为 **完全不依赖 libc** 的桩：`r15src/r15fshim.c`，编法
`arm-linux-gcc -marm -nostdlib -static -shared -fPIC -O2 -fno-builtin`，
自己用 `svc 0` 发 `open(5)/read(3)/write(4)/close(6)/lseek(19)`；`nm -D --undefined-only` = 空，
导出 `Fsys_Init/Exit/Mount/Unmount/Open/Close/Read/Write/Seek/Seek64/GetFileSize/FindFirst/FindNext + mcmn_init`
（= 从 `libsdfileinputupdaterapi.so` / `libupdatercommon.so` 的 undefined 集合精确取，实测这两者的 `U Fsys_*` 列表见 §4）。
日志前缀 **`R15FSHIM`**（写 fd 2）。

## 3. ★反汇编定死的 `Fsys_FindFirst` 真签名（修掉一个真 bug）
`SDFileManager::getFirmwarePath(char* out) @0xda58`（`results_round13/sdpa.asm` 行 5360+）：
```
add.w r6, r0, #12      ; r6 = this+12（1037 B 的路径缓存，入参+出参）
mov   r0, r6           ; arg0 = 路径缓存
movs  r1, #128         ; arg1 = 128（长度）
mov   r2, r7           ; arg2 = sp+8（本地 find 结构，函数栈帧 2096 B）
blx   Fsys_FindFirst@plt
cbz   r0, ok
…  ok: memcpy(out(r8), r6, 1037)   ; ★找到的路径必须写回 **arg0** 缓存
```
⇒ 真签名是 **3 参** `Fsys_FindFirst(char *pathbuf_inout, unsigned len, void *finddata)`，
且**成功后路径写回第一个参数的缓冲区**（调用者只搬这个缓冲区，`finddata` 内容在这条路径上不被使用）。
Round14 的 2 参实现把 260 B 写到了地址 **128** ⇒ guest 里实测崩溃：
`sdfileinput.elf (pid 173) … page translation fault (0x817) at 0x00000080`（`r15_p2_boot1.ser`）——与推断完全吻合。

修好后（`r15_p3`）实测走到：
```
R15FSHIM FindFirst-pattern v=128
R15FSHIM FindFirst-open a=/ramdsk/mnt/BODYDATA.DAT v=4
R15FSHIM FindFirst-ok-path a=0:\BODYDATA.DAT v=0
R15FSHIM Open a=0:\BODYDATA.DAT b=/ramdsk/mnt/BODYDATA.DAT v=0
R15FSHIM Open-size v=346206712          ← 官方 .dat 的真实大小，桩报告成功
R15FSHIM Seek …                         ← 见 §5
UdrAPI,0,SDUUDConditionChecker.cpp:141,"next Chunk seek_point(20) read_size(8) type(56544144) length(4)"
```
`0x56544144` 按小端＝`44 41 54 56`＝**`DATV`** ⇒ **`SDUUDConditionChecker` 正在按我们离线钉死的 UFU 记录链走链**
（`seek_point(20)`＝PROV 记录头位置，`0x14+8+4=0x20` ✓ 与 E1 的容器结构一致）。

## 4. 卡（B）：真 .dat 放哪儿、叫什么
- 卡 = eMMC 镜像 **USER 分区表 index10**（`start 0xb800000`、size `0x1f400000` = 500 MiB、**宿主偏移 `0xbc00000`**）。
  本轮实测修正：Round14 记的 `0xc000000` 是错的（`0xc000000` 挂不上；`0xbc00000` 才挂得上）；guest 里这块叫 **`/dev/nflasha11`**。
- 卡片做法（沿用 Round14）：宿主 `mount -o loop,offset=0xbc00000 <img>` → 往 vfat 根目录写 **`BODYDATA.DAT`**；
  guest `insmod.sh` 里 `loattach /dev/loop0 /dev/nflasha11` + bind 到 `/dev/mmca{,1,aa1}`，`execute_ufp.sh` 里 `mount -t vfat /dev/mmca1 /ramdsk/mnt`
  （本轮实测 `R14B-MOUNT-RC=255`＝**已经挂过了**，`insmod.sh` 的 `R14-TESTMOUNT-RC=0` 已把它常驻挂上，不影响）。
- 卡上文件名：`sdfileinput.elf` 里的字面量 **`BODYDATA.DAT`**；`SDFileManager` 用 `"%c:\%s"` 拼 Fsys 路径
  ⇒ updater 侧真实路径串 = **`0:\BODYDATA.DAT`**（实测在 `R15FSHIM Open` 里看到我们回写的这个串被原样送回）。
  `GetFirmwarePath` 没有再要求别的目录（没有 `SONY/…`、`PRIVATE/…` 之类的路径字面量）。
- 卡内容：`~/Downloads/Update_ILCE7CV200.dmg` → `…/Resources/FirmwareData_ILCE7CV200.dat`（md5 `05862805…`）**未改一字**拷进 vfat 改名 `BODYDATA.DAT`
  （guest 侧 `R15FSHIM Open-size v=346206712` 证明读到的是这个尺寸）。UFU 记录（宿主实测走链）：
  `DATV@0x8(4) PROV@0x14(4) UDID@0x20(172) FDAT@0xd4(size=346,206,480, payload@0xdc … 0x14a2b1ec) DEND@0x14a2b1ec(4)`；
  签名＝FDAT payload 尾 256 B（`0x14a2b0ec..0x14a2b1ec`），消息＝payload[0:size-0x100]。
- 负样本已备好：`a7c_emmc_r15neg.img` = `a7c_emmc_r15.img` 的副本，在**文件偏移 `0x100000dc`**（=FDAT 密文体中段；宿主镜像偏移 `0x1bc000dc`）
  把 `0xde` 翻成 `0xdf`（1 bit）。
- guest 里的公钥 = **官方那把**：`r15/tree/etc/VerificationKey.pem` md5 `ecbe36e0bc00f575c0609e6806985114`
  ＝ `work/l1-camera/a1_initrd/etc/VerificationKey.pem` ⇒ **不需要换键、不需要自签**（E1 作废了 Round14 的自签计划）。

## 5. 现在卡在哪：`Error 42`（`SDUUDConditionChecker`）—— 两个候选原因，第二个已在本轮最后一改里
`r15_p3`（FindFirst 修好、Seek 语义按 `(h, off, whence)`）：
```
R15FSHIM Seek v=0            ← (1, 0, 0) OK
R15FSHIM Seek v=-22          ← (1, 20, 20)：lseek whence=20 → EINVAL
UdrAPI,…:141,"next Chunk seek_point(20) read_size(8) type(56544144) length(4)"
UdrAPI,…:141,"next Chunk seek_point(16777244) read_size(8) type(4000000) length(16777216)"
UdrAPI,…:196610,:130,"Firm size is larger than buffer size. chunk_base.length(1347571542) emptyBufferSize(535293952)"
[FIRMUP NG] : Error 42 ; [sdfileinput.elf] verifyUUDCondition error
```
`r15_p4`（把 Seek 的入参打出来）＝**决定性**：`Fsys_Seek(h=1, off=20, whence=20)` ——
第一参 0 时两个寄存器也都是 0；第二参和第一参**同值**，而 checker 自己的日志说 `seek_point(20)`（绝对位置）。
⇒ 第三个参数**不是** SEEK_CUR/END，`Fsys_Seek` 实际语义更像 **(handle, 绝对位置, 绝对位置/高低位)**。
本轮最后一次改动（`r15fshim_r15e.so`，`initrd_r15e.img`，run `r15_p5`）＝**把 (off==whence)||whence==0 一律按绝对 SEEK_SET 处理**（偏离：真实语义没定死）。
`p5` 结局见文末"补记"（若本轮结束时还没跑完，下一轮第一件事就是看 `r15_p5_boot1.ser`）。

两种可能（都还没定）：
1. **Seek 语义**（上面那条）→ 修好后 checker 就能正确走 UFU 链（DATV/PROV/UDID/FDAT），然后才轮到验签；
2. **卡上文件内容/布局**：checker 在 FDAT 里面又按"每 16 MiB 一个 8 B chunk 头"走链（`type(0x04000000) length(0x1000000)` 出现在 `0x100001C`，
   下一个点直接变垃圾 `length(1347571542)`）⇒ 也可能真机卡的 `BODYDATA.DAT` **不是** DMG 里那个 `.dat` 原样，
   而是**内层再有一层 16 MiB 分块链**（`.dat` 里 FDAT 密文体是整块，不是一串 chunk 头）。这条只能靠真机 dump 更新卡坐实。

## 6. 偏离清单（不代表真机行为）
1. **卡传输层＝假**：QEMU 没有 CXD900x0 PCIe-DME + mcmn SD host；卡＝eMMC 镜像表 index10 的 vfat（宿主 `0xbc00000`），
   guest `loattach`+bind 到 `/dev/mmca{,1,aa1}` 再 `mount -t vfat`。**Sony 自己的 FAT 解析/簇链完全没走。**
2. **Fsys 层＝桩**（`r15/tree/r14bin/r15fshim_r15*.so`，无 libc、裸 `svc`）：`Fsys_Init/Mount/Unmount/Exit/Open/Close/Read/Write/Seek/Seek64/GetFileSize/FindFirst/FindNext` 与 `mcmn_init` 全是我们实现的；
   **`mcmn_init` 返回 0 是伪造**；`Fsys_Mount` 的"有没有卡"= 能不能 `open(CARDROOT/BODYDATA.DAT)`。
3. **`Fsys_FindFirst` 的 find 结构布局未知**：清零 512 B 并把文件名放开头（猜）；这条路径上调用者只用路径缓存 ⇒ 影响小，但不是真机语义。
4. **`Fsys_Seek` 第三参语义没定死**（`p5` 起按绝对定位处理）。`Fsys_Read` 我们循环读满才返回（真机 Fsys 可能返回短读）。
5. **内核退回 `vmlinux_r12.bin`（无 PCIE2_DME）** ⇒ `mmc_drv.ko` 装不上；`execute_ufp.sh::insmodMediaDriver` 被改成**失败不退出**（真机会在这里 `exit 1`）。
   `mcmn_drv.ko` 装载是真 RC=0。
6. initrd 是宿主 `mkfs.cramfs` 打的（gid 截断警告），`/dev` 节点用 `sudo cp -a` 保留；相对 Round14 的 `initrd_r14b` 只改了
   `usr/bin/execute_ufp.sh`（`R15-*` 标记 + 容忍 insmod 失败 + `LD_PRELOAD` 换成 `r15fshim_r15*.so`）。
7. **卡片在宿主 vfat 里（不是真 SD 卡）**；`BODYDATA.DAT` 的**文件名正确性来自反汇编字面量**，但真机卡上"还有没有别的文件/旗标"未知。
8. `p1..p5` 每轮都会让 guest 往 eMMC 副本写（`R13-A23` 探针等）⇒ **实验镜像 md5 会漂**；基线 `a7c_emmc_pt4.img` 一字未动。

## 7. 改动/新增文件与 md5（全部带 r15；基线未动）
基线复验（本轮末）：`a7c_emmc_pt4.img` `8587674613a0ffd86beea010e74fd47c` ✓；
`qemu-system-arm` `e3ae292c…`、`hw/arm/bionz.c` `32dbbd76…`、`hw/sd/sd.c` `e13776d0…`（本轮**没改 QEMU 一行**）。

远端 `~/qemu-a7c/`：
| 文件 | md5 | 说明 |
|---|---|---|
| `run_r15.sh` | （见 results_round15 副本） | `run_r14.sh` 参数化版（tag/img/initrd/kernel/w1/w2/blob/nomode5） |
| `r15src/r15fshim.c` | `6276f75fe0f114795c3d2fffee8b62f2` | 无 libc 的 Fsys 桩源码（终版） |
| `r15src/r15fshim_r15.so` | `2bba9834dcbe376d4b841faeac938838` | FindFirst 3 参修正版（`p3`） |
| `r15src/r15fshim_r15d.so` | `70167bba689fb226ef58b901a5e79a69` | + Seek 入参日志（`p4`） |
| `r15src/r15fshim_r15e.so` | `b95ba49e0fbd21893479be9d6f58b2b2` | + Seek 按绝对定位（`p5`） |
| `initrd_r15a.img` | `11f6cee3f076ca9c55ed3fb81ad90bd3` | 只改 execute_ufp.sh（仍用 r14b 桩 → GLIBC 报错） |
| `initrd_r15b.img` | `3f72e83637430773c9401bc027fff973` | 换成无 libc 桩（`p2`） |
| `initrd_r15c.img` | `0c993ab963f2564db85a8bfdbbbec0b6` | FindFirst 修正（`p3`） |
| `initrd_r15d.img` | `79deae983ebc8affccd753d9cfad2ab5` | Seek 日志（`p4`） |
| `initrd_r15e.img` | `34a654e2413922f637520d72c0571478` | Seek 绝对定位（`p5`） |
| `a7c_emmc_r15.img` | 见文末补记（每轮 guest 会写，md5 会漂） | 卡＝官方 `.dat` 改名 `BODYDATA.DAT`（正样本） |
| `a7c_emmc_r15neg.img` | 见文末补记 | 同上 + 文件偏移 `0x100000dc` 翻 1 bit（负样本，宿主偏移 `0x1bc000dc`：`0xde→0xdf`） |
| `r15/tree/usr/bin/execute_ufp.sh` | `e7ed177e4de504cd50aafc7ec778dfd1` | R15 标记 + 容忍 insmod 失败 + preload 换桩 |
| `r15src/FirmwareData_ILCE7CV200.dat` | `058628057a5d73af90c3a232eac8fb66` | 官方 2.00 `.dat`（scp 上去的，未改一字） |
日志（远端 `~/qemu-a7c/`，副本在 results_round15/）：`r15_t1_boot1.ser`、`r15_t2_boot1.ser`、
`r15_p1_boot1.*`（GLIBC_2.34）、`r15_p2_boot1.*`（FindFirst 崩 @0x80）、`r15_p3_boot1.*`（走到 checker，Error 42）、
`r15_p4_boot1.*`（Seek 入参 = (1,20,20)）、`r15_p5_boot1.*`（Seek 绝对定位）。
`inject_mode5.sh`（每轮往 a2 塞 `updater/mode5`）未改。

## 8. 下一轮起手（顺序写死）
1. 看 `r15_p5_boot1.ser`：Seek 修好后 checker 是否能走完 UFU 链 → 是否出现 `found FDAT` / `Signature Verification Error` / `SDDecryptorModule`。
2. 若仍 `Error 42`：按 §5 假设 2 做**离线**实验——把 `BODYDATA.DAT` 换成
   (a) FDAT payload 本体（去掉 UFU 外层，`dd skip=0xdc count=…`）、(b) `work/v203/full_dec_200.bin`（明文流，头 `UDTRFIRM`）、
   (c) `.dat` + 我们自造的 16 MiB chunk 头链；三张卡各跑一次，看哪张能过 `SDUUDConditionChecker`。
3. 过了 checker 才谈正/负验签：正＝无 `Signature Verification Error`；负（`a7c_emmc_r15neg.img`）＝必须 `Signature Verification Error`（+ 期望 `ApiException 0x30002`）。
4. 写分区闭环（D）需要**带 reboot hook 的内核**：把 ksrc-r13 的 `system.h` 那个 `writel(0x52E57001,0xf240f004)` 补丁搬到 `ksrc-r12`（那颗能完整开机），
   出新 `vmlinux_r15.bin`；否则 `ud_reboot.elf` 在 QEMU 里不回返，只能靠 timeout 重拉。

## 补记（本轮末，p5/p6 的实际结果 —— 详见 `R15_POSTMORTEM.md`）
- `p5`（`Fsys_Seek` 改成按绝对定位后）：**UFU 链走通** → `found FDAT`（`SDUUDConditionChecker.cpp:134`）→
  `Old Version:2.0 / New Version:2.0 Model:0x91030019 Region:0x0000` → `not meet UUD conditions` → **`[FIRMUP NG] : Error 86`**（版本相等不算升级）。
  即 **42 已被 Seek 修正消掉**；拦路点从"卡/总线"变成"版本门"。
- `p6`（卡换成官方 **2.03** `FirmwareData_ILCE7CV203.dat`，md5 `91507fc258de1fd7e8def8b3a6e4dbe7`，镜像 `a7c_emmc_r15v203.img` `c95b9ac0…`）：
  **`New Version:2.3 > Old 2.0` ⇒ UUD 门过**，进入第二次走链 + 取体，`ZZSDREAD` 已 **639,925 条 ≈ 327 MB**（= 整个 FDAT 在流进来）。
  p6 被收尾截断，未看到结局。
- 新增/改动文件 md5 见 §7；POSTMORTEM（写表 / Error 码 / 卡与负样偏移）在
  `work/qemu-a7c/results/round15/R15_POSTMORTEM.md` 与远端 `~/qemu-a7c/results_round16/R15_POSTMORTEM.md`。
