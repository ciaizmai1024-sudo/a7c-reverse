# `/setting`（a2）行为影响与恢复难度

分析对象：ILCE-7C（A7C Gen1，CXD90045）机身 2.00 态，`/dev/nflasha2` 的 FAT12 分区
（`a7c-shared/nflasha2.bin`，19 个文件 + 4 个空目录，共 7,451,043 B）。
地址约定：`init`/内核用 **VA**；共享库/脚本给 **文件偏移**（ELF 的 `.so` VA 通常等于文件偏移，
个别库差 0x8000，表内以文件偏移为准）。"文件偏移"均指该文件自身，不是整块分区。

---

## 0. 一句话结论

**能改变"主系统启动"的只有 5 类**：`kemco.txt`（整条内核 cmdline）、`DmmConfig.bin`（dmm.ko）、
`ulogio.bin`（osal_ulogio.ko）、`mode/dmode` + `mode/preload`（init 的调试/注入开关）、
`env.txt`（init 注入任意环境变量）。`mode/cmode`、`sen/smode` 会改变启动后的模式或是否跑
`sen.elf`，`updater/*` 改变的是 a1 更新器的启动模式；它们一般不会阻止主系统起来
（`dmode=0` 会停在调试 shell）。其余文件影响的是运行期的相机功能、备份/恢复、人脸/安全数据。

按"改坏了救回来的难度"排序（详细表见 §2）：

| 等级 | 含义 | 文件 |
|---|---|---|
| **A 最易** | 正确内容可丢弃/可重写；坏了通常只进调试模式或某功能失效，系统还能起来让你改回来 | `mode/dmode`、`mode/preload`、`mode/cmode`、`sen/smode`、`env.txt`、`gps/assistme.dat`、`updater/*` 开关、`appfw_infra/` |
| **B 中等** | 官方更新包里有逐字节副本，但改错**可能直接开不了机**，需要外部写入/更新器恢复 | `kemco.txt`、`DmmConfig.bin`、`ulogio.bin`（仅 2.03 包有）、`facedmy.bin`、a10 的 `/tmp` 文件（字体/nsswitch 等） |
| **C 最难** | 设备独有，官方包里没有；只能靠自己的整盘 dump，坏了基本不可逆 | `Backup.bin`、`Backup.bak`、`.hasp`、`.etools`、`psd.bin`、`facerec0..7.bin` |

> 注意：`/setting` 里**没有** `sen/` 目录，也没有 `mode/` 下的任何文件（`mode/`、`gps/`、
> `appfw_infra/` 都是空目录）。`dmode`/`cmode`/`smode`/`preload`/`env.txt` 都是"放进去才生效"
> 的 drop-in 文件；本文把它们列出来，是因为它们一旦被创建就是最强的行为开关。

---

## 1. 前提修正

1. **a15 不是 FAT16，是 ext2**：superblock magic `0xEF53`，挂载点 `/usr`。机身没有 `/usr/upper`
   这层路径；`/usr/bin`、`/usr/lib`、`/usr/kmod`、`/usr/scenario` 直接在 a15 根下。
   （`ext2_walk.py` 就是为此写的；`fat12_walk.py` 对 a15 会在 spc=0 处除零。）
2. **`/setting` = a2 = `/dev/nflasha2`**，由 a3 `/system` 上的 `/sbin/init` 在
   `mount_partition()` 里以 `vfat` 挂载，选项 `posix_attr`；挂载表项在 init 文件偏移
   `0x36bc` / VA `0x136bc`。
3. **a1 是更新器分区**（FAT12，8,323,072 B），里面有自己的 `boot/kemco.txt`
   （`console=ttyAM0,115200n8 ...`）和更新脚本；和 a2 的 `kemco.txt` 不是同一个文件。
4. 官方 2.00 包的 `0800_appli/setting/` 四件（`DmmConfig.bin`、`facedmy.bin`、`kemco.txt`、
   `appfw_infra/`）与机身 a2 的对应项尺寸一致；`kemco.txt` 已逐字节核对相同
   （md5 `ef072ecece9be77813e2acae703000b2`，1,905 B）。机身另有 2.03 才引入的
   `ulogio.bin`（3,772 B），是 2.03 包内 3,796 B 文件的前 3,772 B（差异为尾部 24 B）。

---

## 2. 路径 → 读取模块 + 地址 → 能改什么 → 改坏怎么救

### Tier A：删掉/重写即可，坏了不影响开机（按影响从大到小）

| 路径（a2） | 读它的模块 + 地址 | 能改什么 | 改坏怎么救 |
|---|---|---|---|
| `env.txt`（当前不存在） | `/sbin/init` `set_oreore_env()` @ VA `0x98b0`，字符串 VA `0xa77a`；`parse_and_set_env()` @ `0x97cc` | 给 `bootin.elf` 注入**任意环境变量**（`LD_PRELOAD`、`LD_LIBRARY_PATH`、`PATH`…）。按行 `KEY=VALUE`，`#` 注释，单文件上限 1024 B | 删除文件即可；它只在 dmode/debug 路径里被调用 |
| `mode/preload`（不存在） | `/bin/bootin.elf` 文件偏移 `0x26e8`；`/bin/change_mode.sh` 偏移 `0x36` | `LD_PRELOAD` 的库路径；`change_mode.sh p <lib>` 可写任意路径 → 开机在 appFw 里执行任意 `.so` 的构造函数 | 删除文件，或 `echo -n > /setting/mode/preload` |
| `mode/dmode`（不存在） | `/sbin/init` `check_mode_file()` @ VA `0x93b0`，字符串 VA `0xa5bd`；`/bin/bootin.elf` 偏移 `0x2279`；`change_mode.sh` 偏移 `0x15` | 启动层级：`1` 全局 infra、`2` +LIRO、`3` +appFw（默认）、`1n/2n/3n` 非 unified 驱动、`3L` LeakTracer、`3w` sslibc WCheck、`3k` KMC ICE、`3g` target gdb、`3s` gdbserver、`3d` DUMA、`3e` eFence、`3p` 任意 preload；**`0` = 只起内核 + `/bin/ash --login`** | 删除文件（等价默认 3）。若误写 `0` 且没有串口，机器会停在登录 shell，需要外部挂载 a2 删文件 |
| `mode/cmode`（不存在） | `/lib/libObj.so` 偏移 `0x10aa2f4`/`0x10aa318`；`libInfraMediaCommon.so` `0x2b944`；`libInfraMediaDetect.so` `0x10283`；`MPR_SCN_INSTALL_MAP_DEMOMOVIE.so` `0x612e` | 写 `CC` → FactoryMode；缺失/其它 → NormalMode（字符串见 `FactoryMode`/`NormalMode`/`GetFactoryMode()`） | 删除文件 |
| `sen/smode`（不存在，连 `sen/` 目录也没有） | `/sbin/init` `check_forced_senser()` @ VA `0x90fc`，字符串 VA `0xa48a`，判据前两字节 `"UU"`；`/bin/sen.elf` 偏移 `0xb8d3`；多个 lib 也读 | 前两字节 `UU` 且 BIS 条件满足 → 启动时跑 `/usr/bin/sen.elf`；缺失 → 不跑 | 删除文件 |
| `updater/mode`、`mode1`、`mode2`、`mode3`、`mode5`、`mode6`（当前不存在） | a1 initrd `UdtrMain.sh` `getCurrentMode()`：`mode3` @ `0x134`、`mode2` @ `0x1af`、`mode6` @ `0x230`、`mode1` @ `0x2b0`、`mode5` @ `0x32b`；`up.sh` 写这些文件；`libObj.so` 也读 | 选择更新器模式：`mode3`=Minor、`mode2`=Service、`mode6`=VersionSkip、`mode1`=Prod、`mode5`=MSCrypt；**`mode` 不存在会强制 Prod**（`touch /ramdsk/mode1`） | 删除，或用 `up.sh user/serv/ver/ms` 重建；`execute_ufp.sh` 里的 `comp` 标志会在下次更新时 `rm -rf /setting/updater/mode*` |
| `updater/comp`、`updater/debug`、`updater/uincomp`、`updater/MediaUpdateCompleteFlag` | `UdtrMain.sh` `debug` @ `0x614`、`uincomp` @ `0x72f`；`execute_ufp.sh` `comp` @ `0x3f4`、`MediaUpdateCompleteFlag` @ `0x6e4` | `debug`=打开更新器控制台；`uincomp`=下次更新直接报 `ERROR_UINCOMP` 退出；`comp`=下次更新前清掉所有 `mode*`；`MediaUpdateCompleteFlag`=MS Crypt 模式完成标记 | 删除文件 |
| `updater/dat4`（2 B，当前 `00 02`） | `libObj.so` 偏移 `0x102a79a`；`libupdaterufp.so` `0x27b4`；`up.sh` `0x7c1`/`0x911`；更新器 `sauu`/`mf`/`crypter.elf`/`sdfileinput.elf` | 2 字节版本号，文本语义 `"0200"` = 2.00；影响 VersionSkip 的版本比较和更新器 UI | 用 `up.sh modver 0200` 写回；手写 `printf '0200' > /setting/updater/dat4`（无长度/校验） |
| `gps/assistme.dat`（不存在，`gps/` 空） | `/lib/libObj.so` 偏移 `0x102395e`（`/setting/gps/assistme.dat`） | GPS 星历/辅助数据；影响首次定位速度，不影响启动 | 删除；相机会重新下载/重建 |
| `appfw_infra/`（空目录） | 实际日志写在 `/tmp/appfw_infra/ilog_data_%010d.bin`（`libObj.so` 字符串），不是 a2 这个目录 | 本机 dump 里没有内容，不改行为 | `mkdir -p /setting/appfw_infra` |

### Tier B：官方包里有正确字节，但改错可能开不了机

| 路径（a2；a10 `/tmp` 单列一行） | 读它的模块 + 地址 | 能改什么 | 改坏怎么救 |
|---|---|---|---|
| `kemco.txt`（1,905 B，**启动主 cmdline**） | 闭源 loader 把它放到物理 `0x103000`；主内核 `setup_arch()` 补丁 @ VA `0x60499bf4`（文件偏移 `0x391bf4`）先 `strncmp(0x103000,"kemco",5)`，然后就地解析 `0x103005` 起的内容 | 整条内核命令行的**任意标准参数**：`console=`、`root=`、`rdinit=`、`init=`、`initrd=`、`ramdisk_size=`、`mem=`、`memrsv=`、`vmalloc=`、`boottime`、`alog.*`、`pcie*`、`cgroup_disable=`…；以及 Sony 自定义参数：`warm.*`、`cfg.uart`、`wdt.timeout`、`pcie.ch0/1_*`、`tmonitor.*`、`pm.*`、`cmpr.*`、`memrsv`、`wbimem=`、`adrs_conv.*` 等 | 从官方 2.00 包 `0800_appli/setting/kemco.txt` 覆盖（逐字节相同）。**但如果 magic 不对/文件读不到，内核会打印 `invalid cmdline override ... Using default cmdline.`，并沿用零填充的 `default_command_line`（空串）→ 没有 root/initrd → 开不了机**；此时只能靠 a1 更新器/外部写入 a2 恢复 |
| `DmmConfig.bin`（78,284 B） | `/sbin/init` 晚期 `insmod` 表：`dmm.ko` 槽位文件偏移 `0x361c`/`0x3620`，参数字符串 `DmmConfig=/setting/DmmConfig.bin` @ VA `0xb048`；`insmod_drivers()` @ `0x8f8c` | dmm.ko（动态内存管理器）的配置/内存布局；改错可能导致 dmm.ko 初始化失败或内存映射异常 | 官方包 `0800_appli/setting/DmmConfig.bin`（78,284 B，md5 `0963cecccf9069d3d6a97ea985bbe256`）；开不了机时需外部写入。另：`dmm.ko` 还引用可选的 `/setting/DmmConfigExtra.bin`（本机不存在） |
| `ulogio.bin`（3,772 B） | `/sbin/init` 晚期 `insmod` 表：`osal_ulogio.ko` 槽位 `0x35bc`/`0x35c0`，参数字符串 `ulogio_initfile=/setting/ulogio.bin` @ VA `0xaf2b`；更新器 `ulogio.elf` 也处理 ulogio | ULOGIO 的初始记录（例如 `TELN` 记录在 +152，默认关闭）；影响日志/跟踪行为 | 本机 dump 只有 3,772 B；2.03 包内有 3,796 B 版本，前 3,772 B 与机身完全相同（后 24 B 是新增尾部）。2.00 包**没有**这个文件。优先用本机 dump；用 2.03 文件是否完全兼容**未验证** |
| `facedmy.bin`（51,200 B） | `/lib/libObj.so` 偏移 `0x13d3880`；`/scenario/CAMERA_SCN_FACE_REC_DATA.so` 偏移 `0xbe8`（同段还引用 `facerec_.bin`） | 人脸识别"无人脸/默认"占位图；影响人脸注册 UI 的默认显示 | 官方包 `0800_appli/setting/facedmy.bin`（51,200 B） |
| a10 `/tmp`：`nsswitch.conf`、`protocols`、`services`、`toprc`、`mtab`、`config.spec`、`images/*.ltt`、`images/Sony_DI_Icons.ttf` | 用户态：`/etc/nsswitch.conf`（libc）、`/etc/protocols`、`/etc/services`、`/etc/toprc`、`/etc/mtab`（a10 同时承载 `/tmp` 与 `/etc`）；字体由 UI 读取；`config.spec` 读取者**未定位** | 名称解析、服务端口表、top 配置、挂载表占位、UI 字体/图标；`config.spec` 内容为空（0 B），作用未知 | 官方包 `0800_appli/tmp/` 下同名文件（2.00/2.03 尺寸见 §4）；这些文件坏了通常只影响对应功能，不至于开不了机 |

### Tier C：设备独有，官方包里没有；只能靠自己的整盘 dump

| 路径（a2） | 读它的模块 + 地址 | 能改什么 | 改坏怎么救 |
|---|---|---|---|
| `.hasp`（88 B） | `/bin/sen.elf` 偏移 `0x3829`；`/lib/libsencore.so` 偏移 `0x56b9a`；`/lib/libObj.so` 偏移 `0x1028b68` | 安全/license 数据（HASP）；错误时 `sen.elf`/sencore 会报 `Hasp Reset/Read/Write Failed` | **只能用自己的整盘 dump 恢复**；官方包没有。风险最高的设备独有文件之一 |
| `Backup.bin`（1,210,408 B） | `/bin/bk.elf` 偏移 `0x1bc6`；`/kmod/backup.ko` 偏移 `0xae20`（VA `0xec`）和 `0xae60`（VA `0x12c`）；更新器 `mf`/`sauu`/`crypter.elf`/`sdfileinput.elf`；`/sbin/init` 加载 `backup.ko` 时参数是 **`Backup_load=0`**（VA `0xaf03`），所以**开机不会自动恢复** | 设备备份/恢复数据（用户设置、校准等）；损坏影响 bk.elf 的读/写和备份恢复流程，不影响正常开机 | 只能用自己的 dump；与官方标准 blob 有约 100 KB 差异（设备独有）。`Backup_load=0` 意味着开机不读，但 `bk.elf`/更新器会读 |
| `Backup.bak`（1,210,408 B） | 同上；`bk.elf` 偏移 `0x1bda`；`backup.ko` 偏移 `0xa33b`（VA `0x433`） | 上一份备份；与 `Backup.bin` 内容不同（md5 不同） | 只能用自己的 dump；不要用 `Backup.bin` 直接覆盖（语义是"旧备份"） |
| `psd.bin`（4,427,776 B，高熵） | `/lib/CameraOnDemandSaver.so` 偏移 `0x1bf2` | 相机 on-demand saver 的持久化数据（PSD）；具体语义**未证实**；官方 `0100_config/big_backup.conf` 里确实列了 `/setting/psd.bin` | **只能用自己的 dump**；官方包没有。高熵、设备相关，不能靠"重新生成" |
| `.etools`（4,096 B） | `/lib/libsencore.so` 偏移 `0x56b22` | 安全工具配置/license（`libsencore` 读取）；具体格式未知 | **只能用自己的 dump** |
| `facerec0.bin` … `facerec7.bin`（每个 57,888 B） | `/lib/libObj.so` 偏移 `0x13d3854`/`0x13d386a`、`/scenario/CAMERA_SCN_FACE_REC_DATA.so` 偏移 `0xbe8`；注意代码里的名字是 **`facerec_.bin`**，机身实际是 `facerec0..7.bin`，命名映射未完全证实 | 人脸注册记录；`facerec1..7` 当前 7 个完全相同（md5 `07d168c6...`，出厂默认），`facerec0` 不同（md5 `5a37bf61...`，可能是已注册/主记录） | 只能用自己的 dump；不要用 `facedmy.bin` 覆盖（用途不同） |

---

## 3. `kemco.txt` 到底是谁解析、能改到什么程度

### 3.1 解析链（已逐条反汇编确认）

```
闭源 bootloader
  └─ 把 a2 的 kemco.txt 整块放到物理地址 0x103000（PA）
       └─ 主内核 setup_arch() 补丁 @ VA 0x60499bf4 / 文件偏移 0x391bf4
            strncmp(PA+0x000, "kemco", 5)
            ├─ 不等 → printk("<3>setup_arch(): invalid cmdline override @ 0x%08x. Using default cmdline.\n")
            │         并沿用零填充的 default_command_line（空串）→ 没有 root/initrd → 启动失败
            └─ 相等 → 从 PA+5 开始，把 '\n'/'\r' 就地改成空格，扫描最多 0x1000 (4096) B
                      遇到 "换行 + '*'" → 在换行处写 NUL 并停止（'*' 及其后内容不传给内核）
```

要点：

* 文件**必须以小写 `kemco` 开头**（`kemco\n...`）；不是 `KEMCO`。文件名本身是 8.3 的
  `KEMCO.TXT`（LFN `kemco.txt`），改名/改大小写可能让 loader 找不到。
* 文件内部**没有长度、CRC、版本字段**；内核也不校验。唯一的"格式约束"就是上面的 magic、
  换行→空格、`*` 截断、4096 B 上限。
* **文件末尾的单独一行 `*` 是正常的终止符**（stock 文件没有 NUL，靠它停止）。如果删掉 `*`，
  要保证 4096 B 内出现 NUL（或至少文件内容在 4096 B 内结束且 loader 清零了后续缓冲），
  否则解析器会继续读到 PA+4096 之后的垃圾。
* `*` 只在"换行后的第一个字符"才触发截断；行中间的 `*` 不会。
* **loader 侧是否还做校验/是否只认固定文件大小，未证实**（闭源，a1 里没有对应代码）。

### 3.2 支持哪些参数

从主内核 `vmlinux.bin` 能直接抽出两组名字（`kernel_params.py` 可复现）：

1. **Linux `__setup` 标准参数 107 个**（字符串块文件偏移 `0x3b7db4`–`0x3b8230`）：
   `rdinit= init= loglevel quiet debug reset_devices rootdelay= rootfstype= rootflags= rootwait
   root= noatime rw ro load_ramdisk= ramdisk_start= prompt_ramdisk= noinitrd retain_initrd lpj=
   reboot= hlt nohlt em= mem def_priority user_debug= keepinitrd memrsv initrd vmalloc
   use_4kb_mapping mt_uc mt_io noalign ecc nowb nocache cachepolicy wbi_memclr wbimem= xrstreq=
   l2off cpuid em_console relax_domain_level= isolcpus= coredump_filter= oops keep_bootcon
   printk_watchdog_sec= no_console_suspend console= ignore_loglevel log_buf_len iomem= reserve=
   no_file_caps print-fatal-signals= ntp_tick_adj= clock= clocksource= maxcpus nr_cpus nosmp
   cgroup_disable= irqpoll irqfixup noirqdebug hashdist= movablecore kernelcore numa_zonelist_order
   percpu_alloc norandmaps bootmem_debug memblock noaliencache file_nodeorder= noderw= nodero=
   default_nodeorder= nodeorder= dhash_entries= ihash_entries= kstack= gpt elevator= boottime pci
   pcie_aspm= pcie_ports= sysrq_always_enabled secgrp= ramdisk_size= max_loop= alog.clock=
   alog.size= alog.addr= netdev= ether= rhash_entries= thash_entries= uhash_entries= dhcpclass=
   nfsaddrs= ip=`
2. **Sony 自定义参数（点号名）约 150+ 个**，分布在 `.rodata` 0x2c9000 起：
   `warm.*`（`mode`、`tmo`、`chksum`、`errmode`、`cancel`、`boot_drop`、`resume_drop`、
   `ignore_drop`、`mem_dst`、`mem_work`、`chk_opened`）、`cfg.*`（`uart`、`smode`、`poff`、
   `tick_timing`、`abt1`、`abt1_irq`）、`wdt.*`、`pcie.ch0/ch1_*`、`tmonitor.*`、`pm.*`、
   `bam.*`、`pmon.*`、`cmpr.*`、`rmon.*`、`hwbp*`、`page_alloc.*`、`mmu.dac`、`cache_l2x0.*`、
   `pgd.*`、`adrs_conv.*`、`snsc_workqueue.kipid`、`manage.irqd`、`softirq.sirqd`、
   `exception.*`、`klog.*`、`alog.*`、`basic.*`、`stack_usage`、`mmap.debug`、`dma_mapping.l2th`、
   `printk.*`、`spurious.*`、`exec.coremode` 等。
   **这些点号参数的"接受表/校验逻辑"没有完整反汇编出来**（只确认了字符串和它们在
   `kemco.txt` 里实际生效），所以不能保证每个名字都被当前内核接受。
3. 还有第三类：**已内建驱动的 `module_param`**（`模块名.参数=值`）。例如 `kemco.txt` 里的
   `pciehp.pciehp_force=Y`、`pcie_aspm.policy=performance` 不在上面的 `__setup` 字符串块里，
   由模块参数表解析。本次没有把内建模块的参数表全量 dump，所以"全集"还应加上这一类。

### 3.3 关键字的实际效果

| 关键字 | 是否可用 | 说明 |
|---|---|---|
| `console=` | **是**，标准参数 | 当前是 `console=ttynull`（静音）。主内核里有 `AMBA/PL011`、`cxd900x0-uart`、`ttyAM` 字符串，改成 `console=ttyAM0,115200n8` **很可能**能出串口日志；但需要硬件 UART 接入，且当前内核是否注册该 console **未在真机验证** |
| `init=` | **是**，标准参数 | 覆盖 `/sbin/init`。改成不存在的路径/错误程序 → 启动失败。`rdinit=` 同理（initramfs 场景） |
| `root=`、`rootfstype=`、`initrd=`、`ramdisk_size=` | **是** | 当前 `root=/dev/ram0`、`rootfstype=ext2`、`initrd=0x700000,8M`。改错 → 挂不到 root/initrd |
| `single` | **否** | 107 个标准名和 Sony 点号名里都没有 `single`；内核里出现的 `single` 只是函数名（`smp_call_function_single`、`mount_single`）。另外 `/sbin/init` 不读 argv，所以即使传了也没有"单用户"语义 |
| `mem=`、`memrsv=`、`vmalloc=`、`wbimem=` | **是** | 直接改物理内存布局；写错可能硬挂/找不到设备，属于最高风险项 |
| `pm.*`、`pm.ddr_ctrl*`、`pm.pasr*` | 是（Sony 自定义） | 睡眠/恢复/DDR 自刷新参数；写错可能导致休眠唤醒失败 |
| `warm.*` | 是（Sony 自定义） | 热启动/恢复（`warm.mode=2` 等）；写错可能导致唤醒失败 |
| `cmpr.path` | 是 | 指向 `/system/sabin/ssboot.bin`；改错可能影响压缩启动镜像 |

---

## 4. 官方更新包 `0800_appli` 写入清单与下次启动回读

### 4.1 写入清单（tar 成员，2.00 vs 2.03）

| 目标 | 2.00 | 2.03 |
|---|---|---|
| `/setting/DmmConfig.bin` | 78,284 | 78,284 |
| `/setting/appfw_infra/` | 空目录 | 空目录 |
| `/setting/facedmy.bin` | 51,200 | 51,200 |
| `/setting/kemco.txt` | 1,905 | 1,905 |
| `/setting/ulogio.bin` | — | **3,796（新增）** |
| `/tmp/config.spec` | 0 | 0 |
| `/tmp/images/MYingHeiC-Big5-SJ_wIcon.ltt` | 1,150,740 | 1,150,740 |
| `/tmp/images/MYingHeiC-GB18030-SJ_wIcon.ltt` | 1,958,432 | **2,054,740** |
| `/tmp/images/Sony_DI_Icons.ttf` | 566,836 | **619,664** |
| `/tmp/mtab` | 2 | 2 |
| `/tmp/nsswitch.conf` | 261 | 261 |
| `/tmp/protocols` | 2,859 | 2,859 |
| `/tmp/services` | 19,666 | 19,666 |
| `/tmp/toprc` | 617 | 617 |
| `/tmp/kikilog.dat` | — | **1,957,888（新增）** |

落地位置证据：

* a2 机身 dump 的 `DmmConfig.bin` / `facedmy.bin` / `kemco.txt` 尺寸与 2.00 包完全一致，
  `kemco.txt` 逐字节相同；更新器又用 `us_crc32sum_appli.sh` 把 `/dev/nflasha2` 挂成
  `appli_sum/setting`，因此 `0800_appli/setting/*` 的落点是 a2 `/setting/*`。
* a10 机身 dump 在 `+0x47fe40` 处出现 2.03 的 `kikilog.dat` 头 512 B，说明
  `0800_appli/tmp/*` → a10 文件系统（a10 同时承载 `/tmp` 和 `/etc`）。
* 更新器的 `us_crc32sum_appli.sh` 把 `/dev/nflasha2` 挂成 `appli_sum/setting` 后跑
  `uc_crc32sum.elf -c appli.sum`；`uc_crc32sum.elf` 是否真的校验设备侧文件（还是只校验包内
  `_sum`）**未完全证实**（见 §6）。

### 4.2 下次启动会被谁读回去

| 文件 | 下次启动读取者 | 时机 | 备注 |
|---|---|---|---|
| `/setting/kemco.txt` | 闭源 loader → 内核 `setup_arch()` @ `0x60499bf4` | 最早，内核启动前/中 | 改错 → 空 cmdline → 启动失败 |
| `/setting/DmmConfig.bin` | `/sbin/init` 晚期 insmod `dmm.ko`（槽位 `0x361c`，参数 VA `0xb048`） | 内核起来后、appFw 前 | dmm 初始化失败可能影响后续所有进程 |
| `/setting/ulogio.bin` | `/sbin/init` 晚期 insmod `osal_ulogio.ko`（槽位 `0x35bc`，参数 VA `0xaf2b`） | 同上 | 2.00 机身也有（3,772 B，来自 2.03 前缀） |
| `/setting/facedmy.bin` | `libObj.so` / `CAMERA_SCN_FACE_REC_DATA.so` | 运行期（人脸 UI/识别） | 不参与启动 |
| `/tmp/kikilog.dat` | `/kmod/kikilog.ko`（字符串 `/tmp/kikilog.dat`，偏移 `0x5285`） | 模块加载时 | 2.03 才写；2.00 机身没有 |
| `/tmp/images/*`、`/tmp/nsswitch.conf`、`/tmp/protocols`、`/tmp/services`、`/tmp/toprc`、`/tmp/mtab` | UI / libc / top / mount 工具 | 运行期 | `/tmp` 与 `/etc` 同源 |
| `/tmp/config.spec` | **未定位** | — | 0 B，先标未知 |
| `/setting/appfw_infra/` | 无（日志实际写 `/tmp/appfw_infra/`） | — | 空目录，无影响 |

---

## 5. 其他 `/setting` 读取者（运行期功能，列全供排查）

| 路径 | 读取模块（文件偏移） | 作用/备注 |
|---|---|---|
| `/setting/Backup.bin`、`Backup.bak` | `/bin/bk.elf` `0x1bc6`/`0x1bda`；`backup.ko` `0xae20`/`0xae60`/`0xa33b`；更新器 `mf`、`sauu`、`crypter.elf`、`sdfileinput.elf` | 备份/恢复；开机 `backup.ko` 参数 `Backup_load=0`，不自动恢复 |
| `/setting/psd.bin` | `/lib/CameraOnDemandSaver.so` `0x1bf2` | 相机 on-demand saver；设备独有 |
| `/setting/.hasp` | `/bin/sen.elf` `0x3829`；`libsencore.so` `0x56b9a`；`libObj.so` `0x1028b68` | HASP/安全 |
| `/setting/.etools` | `libsencore.so` `0x56b22` | 安全工具配置 |
| `/setting/facerec_.bin`（代码名） / `facerec0..7.bin`（实际名） | `libObj.so` `0x13d3854`/`0x13d386a`；`CAMERA_SCN_FACE_REC_DATA.so` `0xbe8` | 人脸记录 |
| `/setting/facedmy.bin` | `libObj.so` `0x13d3880`；同场景 | 默认人脸图 |
| `/setting/IPTC_001.XMP`（不存在） | `libInfraIPTC.so` `0x14ddf` | 可选 IPTC 模板 |
| `/setting/DmmConfigExtra.bin`（不存在） | `dmm.ko` `0xdb90`（VA `0x1f`） | 可选 dmm 额外配置 |
| `/setting/mode/cmode` | `libObj.so` `0x10aa2f4`/`0x10aa318`；`libInfraMediaCommon.so` `0x2b944`；`libInfraMediaDetect.so` `0x10283`；`MPR_SCN_INSTALL_MAP_DEMOMOVIE.so` `0x612e` | Factory/Normal |
| `/setting/mode/smode`？ | 实际代码用 `/setting/sen/smode`（`libInfraMediaCommon.so` `0x2b95c`、`libInfraRemote.so` `0x7a8278`、`libInfraUsbCmn.so` `0x1283e`、`libObj.so` `0xe7d866` 等） | 注意：不是 `mode/smode` |
| `/setting/sen/` | `sen.elf` `0x390d`、`libsencore.so` `0x56c7e`、`libObj.so` `0x1028c39`、`MPR_SCN_INSTALL_MAP_DEMOMOVIE.so` `0x60fa` | 目录本身（本机不存在） |
| `/setting/updater/mode1`/`mode3`/`mode6`/`mode` | `libObj.so` `0x1028dfe`/`0x1028e15`/`0x1028e2c`/`0x1028e85` | 更新器状态回读 |
| `/setting/updater/dat4` | `libObj.so` `0x102a79a`；`libupdaterufp.so` `0x27b4`；`up.sh` | 版本号 |
| `/setting/updater` | `libObj.so` `0x1029082` | 目录 |
| `/setting/gps/assistme.dat` | `libObj.so` `0x102395e` | GPS 辅助数据 |
| `/setting/env.txt` | `/sbin/init` `set_oreore_env` VA `0x98b0`（字符串 VA `0xa77a`） | 任意环境变量 |
| `/setting`（目录本身） | `/sbin/init` `0x298f`/`0x2c67`；`im.elf` `0x42d0`；`sen.elf` `0x386d`；`libsencore.so` `0x388ba`/`0x56bde`；`libObj.so` `0x1028bac` | 挂载点/存在性检查 |

---

## 6. 不确定/未证实（明确标出）

1. **loader 侧**：闭源 bootloader 如何选择 `kemco.txt`、是否校验大小/CRC/版本、是否只认固定
   LFN/8.3 名，均未证实。内核侧只看到 magic + 4096 B + `*` 截断。
2. **Sony 点号参数接受表**：名字能从 `.rodata` 抽出 150+ 个，但"哪些会被解析器接受、默认值、
   范围校验"没有完整反汇编；不能保证手工写一个未出现过的点号名会生效。
3. **`uc_crc32sum.elf`**：确认它读 `appli.sum` 并对 `/dev/nflasha2` 挂载点工作，但是否逐文件
   校验设备侧内容（而不是只校验包内 `_sum`）未证实；`0x82` LED 错误码的触发条件也未证实。
4. **`psd.bin` 语义**：只确认 `CameraOnDemandSaver.so` 读它、官方 `big_backup.conf` 列它；
   具体数据结构/能否重建未证实。
5. **`facerec_.bin` vs `facerec0..7.bin`**：代码字符串是 `facerec_.bin`，机身实际是 0..7；
   `facerec0` 与 1..7 的 md5 不同，是否"0 = 主记录"未证实。
6. **`Backup.bin` 的运行期消费者**：除 `bk.elf` 和更新器工具外，是否还有后台服务读它，未穷尽。
7. **`DmmConfig.bin` 结构**：只确认 dmm.ko 吃它；字段语义未解析。
8. **`/setting/appfw_infra/`**：a2 上是空目录，实际日志写 `/tmp/appfw_infra/`；这个空目录是否
   被某模块当挂载点/存在性检查，未证实。
9. **`config.spec`**：0 B，读取者未定位。
10. **a15 尾部 74.6 MB**：不在官方包内（用户数据区），本文没有覆盖。
11. **`console=ttyAM0` 真机可用性**：主内核有 AMBA/PL011 和 `ttyAM` 字符串，但没有真机串口
    实测；不排除 UART 引脚/时钟未配置。
12. **`/setting/sen/` 的创建者**：本机 dump 没有该目录；谁会在什么条件下创建它（服务工具/
    某些地区机型）未证实。

---

## 7. 脚本与证据文件

本目录：

| 文件 | 用途 |
|---|---|
| `ext2_walk.py` | 遍历 a15 ext2（a15 不是 FAT16；用 superblock magic `0xEF53`） |
| `scan_strings.py` | 在二进制/目录树里扫字符串并输出 `路径 文件偏移 VA 字符串` TSV |
| `kernel_params.py` | 从裸 `vmlinux.bin` 抽标准 107 个参数、Sony 点号参数、KEMCO 补丁地址/PA/4096 上限；`--disasm` 可出反汇编 |
| `a15_hits.tsv` | a15（`/usr`）全量 `/setting`、`/tmp` 字符串命中 |
| `a1_initrd_200_hits.tsv`、`a1_initrd_203_hits.tsv` | 更新器 initrd 2.00/2.03 命中 |
| `a3_initrd_hits.tsv` | a3 `/system`（含 `/sbin/init`）命中 |

复现命令：

```bash
python3 ext2_walk.py ../a7c-shared/nflasha15.bin /tmp/a15walk
python3 scan_strings.py ...            # 见脚本内 usage
python3 kernel_params.py ../a3/out/extracted/vmlinux.bin
python3 kernel_params.py ../a3/out/extracted/vmlinux.bin --disasm | sed -n '/KEMCO/,$p'
```

关键地址速查：

* 主内核 KEMCO 补丁：VA `0x60499bf4` / 文件 `0x391bf4`；magic `"kemco"` VA `0x6044fbf4`；
  PA `0x103000`；上限 `0x1000`；`*` 截断。
* `/sbin/init`：`check_mode_file` `0x93b0`、`check_forced_senser` `0x90fc`、
  `set_oreore_env` `0x98b0`、`parse_and_set_env` `0x97cc`、`parse_cmdline` `0x9694`、
  `insmod_drivers` `0x8f8c`、`main` `0x9a10`；`/setting` 挂载表项 `0x136bc`。
* `dmm.ko` 参数 `DmmConfig=/setting/DmmConfig.bin` VA `0xb048`（insmod 槽位 `0x361c`）；
  `osal_ulogio.ko` 参数 `ulogio_initfile=/setting/ulogio.bin` VA `0xaf2b`（槽位 `0x35bc`）；
  `backup.ko` 参数 `Backup_load=0` VA `0xaf03`（槽位 `0x35b4`）。

---

## 8. 通用抢救步骤（按可用性从好到坏）

0. **动手前先整盘备份 a2**：机身能起时 `dd if=/dev/nflasha2 of=/tmp/a2.bin bs=1M`（或直接保存
   `nflasha2.bin`），并记下 md5。Tier C 的文件没有第二份来源，备份是唯一保险。
1. **系统还能起**：`mount -t vfat -o posix_attr /dev/nflasha2 /setting` → 删除/重写目标文件 →
   `sync`。优先用"删除"而不是"写坏值"：Tier A 的文件删除后都回到默认行为。
   `dmode` 改坏可用 `/bin/change_mode.sh 3` 恢复；`preload` 用 `echo -n > .../preload` 清空。
2. **改 `kemco.txt` 前先离线模拟**：确认文件以 `kemco` 开头、结尾有 `*` 行、总长 < 4096 B；
   可用本目录的解析逻辑（见 §3.1）先跑一遍，确认生成的 cmdline 里有 `root=`、`initrd=`、
   `init=`，再写回。改完不要立刻重启，先 `sync` 并保留原文件副本。
3. **主系统起不来、但更新器还能进**：用 a1 的更新模式重刷官方包；注意
   `updater/mode*` 和 `updater/comp` 的语义（§2 Tier A）。更新器只保证包内文件，
   **不会恢复** `Backup.bin`/`psd.bin`/`.hasp`/`.etools`/`facerec*` 这些设备独有数据。
4. **完全起不来**：只能外部读写 a2（eMMC/NAND dump、编程器或厂商服务工具）。恢复顺序：
   `kemco.txt` → `DmmConfig.bin` → `ulogio.bin` → 其它；**不要用官方 2.00 包整体覆盖 a2**，
   否则会丢掉 Tier C 的设备独有文件。
5. 任何一步之后如果相机行为异常但能起，先检查 `/setting` 里是否多出了不该存在的
   `mode/dmode`、`mode/preload`、`env.txt`、`updater/*` 标志文件。
