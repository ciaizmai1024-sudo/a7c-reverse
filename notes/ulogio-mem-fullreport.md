# ulogio 内存读写：地址空间、限制、SID/SA 映射（A7C 2.00）

对象：`/bin/ulogio.elf`（CLI）、`/lib/libosal_ulogio.so`、`/kmod/osal_ulogio.ko`，
配置 `/setting/ulogio.bin`（`a7c-shared/setting/ULOGIO_BIN`，3772 B）。

所有地址默认写成 **物理地址（PA）**，除非明确标了 VA。
本文的 PA 都来自 `logaddr` 同一条转换链，不是猜的。

---

## 0. 五个问题的直接回答

1. **地址是物理还是虚拟？走 ioremap 吗？**
   **物理地址（PA）**。`db/dw/dl/dk`、`mb/mw/ml/mf/mu` 都是 CLI 自己打开
   `/dev/mem`、`mmap` 后直接读写；**CLI 侧不经过内核模块，也不做
   ioremap**。mmap 的 offset 就是 PA；`pagebase = addr & ~0xfff`，
   页内偏移单独加。
   `logaddr` 的输出也是 PA：内核在回复前做了 VA→PA 归一化（见 §1）。

2. **有范围检查、掩码、白名单、子系统门禁、写保护吗？**
   **没有。** 只有**对齐检查**：
   - `db/dk/mb/mf/mu`：1 字节对齐（等于不检查）
   - `dw/mw`：必须偶数
   - `dl/ml`：必须 4 字节对齐
   掩码只用来判对齐，不做地址裁剪。没有白名单、没有窗口限制、不需要先
   `switch` 进任何子系统。软件层**没有写保护**；唯一可能的保护是内核
   `/dev/mem` 策略（`CONFIG_STRICT_DEVMEM`，本机未知，见 §8）。
   注意：只有 `logaddr` 在服务侧校验 SID/area；`db/dw/dk/mb/...` 完全
   绕过那张表，给什么 PA 就访问什么 PA。

3. **`logaddr [SID][SA]` 后面的表能列出来吗？有没有 av-cam/DSP 地址？**
   能。表是数据驱动的：`/setting/ulogio.bin` 里的 `SUBS` 记录 → 启动时
   `ulogio_lbm_init()` 在日志缓冲里建描述符和区域。2.00 一共
   **109 个 SID、417 个区域**，全部落在
   **PA `0x030850d8`–`0x034bd190`**（DDR0 内的保留 RAM）。
   **表里没有任何 av-cam/DSP 地址。** 完整 417 行见
   `sid_table_200.tsv`，109 行汇总见 §4。
   `0x635C6000` **不是 ARM PA**，直接喂给 `db` 会落到物理空洞
   `0x40000000–0x7FFFFFFF`，可能锁总线（详见 §1.3）。

4. **`dk` 的导出路径任意吗？有大小上限吗？**
   路径**任意**（字符串直接进 `open`，长度受 0x80 命令行缓冲限制，
   见 §5.1），flags = `0x642`
   （`O_RDWR|O_CREAT|O_TRUNC|O_APPEND`），mode `0644`。
   大小 = 用户给的字节数，**没有上限**；只受 `mmap` 和物理地址有效性限制。
   如果范围跨进无效 PA，进程会挂死/整机挂死，而不是报错。

5. **`switch` 进子系统菜单后命令集变吗？**
   变的不是“同一套 db/dw”。`switch` 是一个 **UIPC 透传菜单**：
   进菜单后，除了 `uquit`（本地退出）之外，**每一行都原样转发给子系统**，
   由子系统自己解释。本地没有 `db/dw`。子系统的命令集**不在**这三个文件里，
   所以无法从现有材料确认（列入 §8）。

---

## 1. 地址模型：PA、VA、和 `0x635C6000` 的坑

### 1.1 内核线性映射常量

来自 `a7c-shared/notes/qemu.md` 与 GPL 源码：

```
PAGE_OFFSET = 0x60000000      # DDR0 的线性映射起点
SIZE_DDR0   = 0x40000000      # 1 GB
VA_DDR1     = 0xA0000000      # PAGE_OFFSET + SIZE_DDR0
DDR1_BASE   = 0x80000000      # 第二片 DRAM 的物理基址（主系统）
```

所以：

```
VA → PA： VA <  0xA0000000  ⇒  PA = VA - 0x60000000
          VA >= 0xA0000000  ⇒  PA = VA - 0x20000000
PA → VA： PA <  0x80000000  ⇒  VA = PA + 0x60000000
          PA >= 0x80000000  ⇒  VA = PA + 0x20000000
```

这两条都在模块里有对应指令：

- `ulogio_get_logaddr` 的归一化在 `.ko` `0x1b68`：
  `cmn r3,#0x60000001 / addls #0xA0000000 / addhi #0xE0000000`
  —— 就是上面的 VA→PA（加 0xA0000000 等于减 0x60000000，模 2³²）。
- `ulogio_resume` 在 `.ko` `0xe04` 做反向 PA→VA：
  `cmp r0,#0 / addge #0x60000000 / addlt #0x20000000`。

**结论：`logaddr` 打印出来的数就是 PA，可以直接给 `db/dw/dl/dk`。**
CLI 自己的帮助字符串也写得很直白：
`logaddr [SubSystemID][SubArea] -- get log memory physic address .`

### 1.2 数值相同、含义不同

| 数值范围 | 当 **PA** 用 | 当内核线性映射 **VA** 用 |
|---|---|---|
| `0x00000000–0x3FFFFFFF` | DDR0 1 GB（含若干保留洞） | 不是 VA（低地址不是线性映射） |
| `0x40000000–0x5FFFFFFF` | **主系统物理空洞** | 不是 VA |
| `0x60000000–0x9FFFFFFF` | **物理空洞** | DDR0 线性映射（对应 PA `0x00000000–0x3FFFFFFF`） |
| `0xA0000000–0xAFFFFFFF` | 无 DRAM（DDR1 物理在 `0x80000000`） | DDR1 线性映射（对应 PA `0x80000000–0x8FFFFFFF`） |
| `0xB0000000–0xFFFFFFFF` | 无 DRAM / 设备区 | vmalloc（起点 `0xB0800000`）/ 模块 / 保留，非 DRAM 线性映射 |

### 1.3 `0x635C6000` 到底是什么

- 作为 **PA**：`0x635C6000` 在 `0x40000000–0x7FFFFFFF` 的空洞里，
  **不在任何 ARM `mem=` 窗口**。`db 0x635C6000 ...` 会打到无 DRAM 的
  AXI 地址，轻则 external abort（进程/内核 oops），重则总线挂死。
- 作为 **ARM 内核 VA**：它属于 DDR0 线性映射，按公式
  `PA = 0x635C6000 - 0x60000000 = 0x035C6000`。
- 作为 **DSP 平铺地址**：`liro.ko` 把 `av-cam.bin` 放在 DSP 地址
  `0x635C6000`（入口 `0x635C6044`）。**DSP 可能有自己的 MMU/重映射**，
  不能仅凭 ARM 的线性映射就断言它的物理背面是 `0x035C6000`。
  `0x035C6000` 确实落在主系统 `memrsv=0x1A5E000@0x02E68000`
  （`0x02E68000–0x048C6000`）的保留 RAM 里，但这只能说明“可能”，
  不能证明 DSP 用的就是这一页。

**上机规则：永远不要给 `db/dw/dl/dk/mb/...` 喂 `0x6xxxxxxx`。
要么用 `logaddr` 拿 PA，要么用手工换算后的 `0x0xxxxxxx`，并且确认它落在
§3 的“可读”区。想碰 DSP 镜像，走 liro/文件侧，不要走 `/dev/mem`。**

---

## 2. 命令实现与限制（代码证据）

### 2.1 读命令 `db / dw / dl / dk`

CLI 处理函数 `ulogio.elf:0xa524`（命令表在 `0x141e0`，36 项 × 24 B）。
参数规格与单位：

| 命令 | id | 参数 | 读写宽度 | 说明 |
|---|---:|---|---|---|
| `db` | 1 | `addr size` | 1 B | 每行 16 字节，不可打印字符打成 `.` |
| `dw` | 2 | `addr size` | 2 B | 地址必须偶数 |
| `dl` | 3 | `addr size` | 4 B | 地址必须 4 字节对齐 |
| `dk` | 4 | `addr size path` | 1 B | 原始字节写入文件 |

`size` **一律是字节数**，不是元素个数。
例：`dl 0x0308503c 12` 读 12 字节 = 3 个 32 位字。

实现细节：

```
open("/dev/mem", O_RDONLY)                    # flags = 0
pagebase = addr & ~0xfff
p = mmap(NULL, size + (addr & 0xfff), PROT_READ, MAP_SHARED, fd, pagebase)
读 p + (addr & 0xfff)
```

没有范围检查；`size` 只受 `mmap` 长度和 32 位参数解析限制。

### 2.2 写命令 `mb / mw / ml / mf / mu`

CLI 处理函数 `ulogio.elf:0x9808`。

| 命令 | id | 参数 | 写入宽度/行为 | 对齐 |
|---|---:|---|---|---|
| `mb` | 6 | `addr value` | 1 B | 无 |
| `mw` | 7 | `addr value` | 2 B（取低 16 位） | 偶数 |
| `ml` | 8 | `addr value` | 4 B | 4 字节 |
| `mf` | 9 | `addr size byte` | 从 addr 起填 `size` 个 `byte` | 无 |
| `mu` | 10 | `addr size file` | 把文件内容复制到 PA | 无 |

```
open("/dev/mem", O_RDWR)                      # flags = 2
p = mmap(NULL, len + (addr & 0xfff), PROT_READ|PROT_WRITE,
         MAP_SHARED, fd, pagebase)
mb/mw/ml: 直接 strb/strh/str 到 p + offset
mf:       逐字节填充（strb 循环）
mu:       open(file, O_RDONLY) → lseek(END) → len = min(size, filesize)
          → mmap(file, len, PROT_READ, MAP_SHARED, fd, 0)
          → memcpy(p + offset, filemap, len)
最后 munmap / close
```

**没有写保护、没有只读白名单、没有“先 switch”要求。**
写错地址的后果和读错一样：MMIO 可能直接改变硬件状态，空洞可能挂总线。

### 2.3 参数解析的两个坑

- 命令首 token 会**转成大写**再做哈希匹配，所以 `db`/`DB` 都行。
- 数字词法：带 `0x`/`0X` 前缀 → 十六进制（base 16），否则 → 十进制
  （base 10）。**不支持前导 `0` 的八进制**：`0308503c` 在 `0` 后面
  紧跟数字时直接判为非法 token。所以**地址和长度一律写 `0x...`**。
- 解析器会检查 32 位溢出；超过 `0xFFFFFFFF` 的参数会被拒绝。
- 纯字母开头的 token 只有在参数规格是字符串时才有意义（如 `dk` 的路径）；
  数值参数必须以数字或 `0x` 开头。

### 2.4 相关字符串/常量

| 用途 | 位置/字符串 |
|---|---|
| 对齐错误 | `[ulogio] address not aligned to boundary ` (`0xb080`) |
| 打不开 /dev/mem | `[ulogio] failed to open /dev/mem ` (`0xb0b8`) |
| mmap /dev/mem 失败 | `[ulogio] failed to map /dev/mem ` (`0xb0dc`) |
| dk 打不开目标文件 | `[ulogio] failed to open data file ` (`0xb060`) |
| mu 源文件 mmap 失败 | `[ulogio] failed to map data file ` (`0xb100`) |

---

## 3. “能读哪些地址、怎么写、有什么限制”总表

内存窗口来自主系统（a2）kemco 命令行：

```
mem=1G@0
memrsv=1M@0
memrsv=0x8000@0xF00000
memrsv=0x1A5E000@0x02E68000
memrsv=0xAEEB000@0x0A915000
memrsv=680M@0x15800000:uc
mem=256M@0x80000000@1
memrsv=256M@0x80000000:uc
```

| PA 范围 | 内容 | 读 | 写 | 依据/备注 |
|---|---|---|---|---|
| `0x03085000–0x034FD000` | ulogio 日志缓冲（LOGB）：cfg 头 + 描述符 + 417 个 RBUF 区 | **推荐** | **不要写** | 本表全部地址在这里；写坏 RBUF 指针可让 ulogio 崩 |
| `0x00000000–0x00100000` | DDR0 低 1 MB（`memrsv`；含内核页表/异常向量） | 一般可读 | 不要写 | `memrsv=1M@0` |
| `0x00100000–0x00F00000` | DDR0 内核/用户 RAM | 可读 | 谨慎 | `mem=1G@0` |
| `0x00F00000–0x00F08000` | tmonitor 缓冲（保留） | 可读 | 不要写 | `memrsv=0x8000@0xF00000` |
| `0x00F08000–0x02E68000` | DDR0 RAM | 可读 | 谨慎 | |
| `0x02E68000–0x048C6000` | 保留 RAM（ulogio 日志、`klog=0x035A5000`、`alog=0x03524FC0` 等） | 可读 | 仅日志区按需 | `memrsv=0x1A5E000@0x02E68000` |
| `0x048C6000–0x0A915000` | DDR0 RAM | 可读 | 谨慎 | |
| `0x0A915000–0x15800000` | 保留区（用途未确认） | 可读 | 不要写 | `memrsv=0xAEEB000@0x0A915000` |
| `0x15800000–0x40000000` | 680 MB uncached 保留（可能是 DSP/ISP/相机，未确认） | **不保证**（可能在 DMA 中，读有副作用风险） | **禁止** | `memrsv=680M@0x15800000:uc` |
| `0x40000000–0x7FFFFFFF` | 主系统物理空洞（DDR1 不在这里） | **禁止** | **禁止** | 可能锁总线；`0x635C6000` 落在这里 |
| `0x80000000–0x8FFFFFFF` | DDR1 256 MB | 物理上存在，读有风险 | **禁止** | `mem=256M@0x80000000@1` + `memrsv=256M@...:uc` |
| `0x90000000–0xFFFFFFFF` | 无 DRAM / 设备区 | **禁止** | **禁止** | 无映射资料 |

“可读”只表示**大概率不会立刻挂总线**，不表示数据有意义。
真正推荐上机读的，只有 `logaddr` / 本表给出的**日志区域**。

### 3.1 只读、只写、和“绝对不要碰”

- **只读（安全）**：`0x030850d8–0x034bd190` 里的 417 个区域。
- **只读（一般安全）**：DDR0 的普通 RAM（`0x00100000–0x15800000`，避开保留洞）。
- **只读（有风险）**：DDR1（`0x80000000–0x8FFFFFFF`）、680 MB 保留区
  （`0x15800000–0x40000000`）。
- **绝对不要读写**：`0x40000000–0x7FFFFFFF`（主系统物理空洞）、
  `0x90000000–0xFFFFFFFF`（DDR1 之后无 DRAM / 设备区，尤其 MMIO）、
  以及任何 `0x6xxxxxxx` / `0xAxxxxxxx` 的**数值当作 PA** 直接传入。

### 3.2 写内存

- 命令：`mb/mw/ml/mf/mu`（见 §2.2）。
- 限制：只有对齐；没有范围检查、没有写保护。
- 值也要带 `0x` 才是十六进制；`mw` 只取低 16 位，`mb` 只取低 8 位。

```
# 语法示例（地址只是演示，写前先确认该页不被驱动/DMA 使用）
mb 0x030850fc 0x00              # 1 字节
mw 0x030850fc 0x1234            # 2 字节，地址必须偶数
ml 0x030850fc 0x12345678        # 4 字节，地址必须 4 对齐
mf 0x030850fc 0x100 0x00        # 从地址起填 0x100 个 0x00
mu 0x030850fc 0x100 /tmp/x.bin  # 文件内容复制到 PA
```

- 建议：**先 `dk` 备份同一段，再写**；写日志区之外前先确认该页不被
  DMA/驱动使用；写 RBUF 头或描述符等于给 ulogio 埋雷。
- `mu` 的源文件路径任意可读；写入长度会被夹到文件大小。

---

## 4. SID / SA 对照表

### 4.1 表是怎么来的

`/setting/ulogio.bin` 是 TLV：`total_len(4) + tag(4) + payload`。
`SUBS` 记录 payload：

```
+0x00 u32 sid
+0x04 u32 total_size
+0x08 u32 area_size[count]      # bit31 = flag
```

`osal_ulogio.ko:ulogio_lbm_init`（`0x1fe0`）在日志缓冲
`LOGB.base + 60` 处顺序建描述符：

```
descriptor (20 + 8*count 字节)
+0x00 u32 "SUBS"       = 0x53425553
+0x04 u32 sid
+0x08 u32 total_size
+0x0c u16 (未初始化/通常 0)
+0x0e u16 count
+0x10 u16 flag_count
+0x12 u16 0
+0x14 area[count] { u32 size, u32 base_kva }
```

- `area` 表里的 `base` 是**内核 VA**（`0x6xxxxxxx` / `0xAxxxxxxx`）。
  `logaddr` 返回前会做 VA→PA；**用 `db` 直接看描述符时看到的是 VA**。
- 区域数据块：`base` 指向 36 字节 RBUF 头，真正数据从 `base+36` 开始，
  长度 `size-36`。`logaddr` 返回的是 **base（头）和整块 size**，
  **不是**数据起点。
- 2.00 实测：`LOGB.base=0x03085000`、`size=0x00478000`，
  arena `0x0308503c`，最后一个区域 end `0x034bd190`，
  已用 `0x438154`，剩余 `0x3FEAC`。
- 109 个 SID 的描述符头+区域表合计 `0x158C`，区域块合计 `0x436BC8`，
  相加正好 `0x438154`，与 config 的 `sum(total_size)` 完全对上。
- **注意**：`a7c-shared/notes/ulogio-format.md` 里“2.00 有 110 个 SUBS”
  是笔误；配置里 `SUBS` 原始字节只出现 **109** 次，2.00 实际 **109**。

### 4.2 描述符/区域头的实测校验值

第一个描述符就是 SID `0x83`：

| 读法 | 预期 |
|---|---|
| `dl 0x0308503c 12` | `53425553 00000083 00080340` |
| `dw 0x0308504a 2` | `0011`（count=17，描述符 +0x0e） |
| `dw 0x0308504c 2` | `0002`（flag_count=2，描述符 +0x10） |
| `dl 0x03085050 8` | `00001024 630850D8`（SA0 的 size/base-KVA，描述符 +0x14） |
| `dl 0x030850d8 36` | `46554252 630850FC 00001000 00000FFF 630850FC 630850FC 630850FC 00000000 00000000`（RBUF 头，指针是 KVA） |

说明：
- `53425553` = 小端 dword 的 `"SUBS"`；`46554252` = `"RBUF"`。
- RBUF 头布局：`+0` magic、`+4` 数据指针、`+8` `size-36`、
  `+0xc` `size-37`、`+0x10/+0x14/+0x18` 三个数据指针、`+0x1c/+0x20` 0。
- SID `0x83` 的 SA0：base `0x030850d8`，整块 `0x1024`，
  数据 `0x030850fc`–`0x030860fc`（`0x1000` 字节）。
  这也正好是 `LOGB.base+60` 后第一个描述符的 `20+8*17` 字节头之后的位置。

### 4.3 `logaddr` 的用法

```
logaddr 0                      # 0x03085000 / 0x47803c
logaddr 0x83                   # 0x0308503c / 0x00080340（描述符地址 + total_size）
logaddr 0x83 0                 # 0x030850d8 / 0x00001024（SA0 的 RBUF 头地址 + 整块 size）
logaddr 0x83 0xffffffff        # 显式 area=-1，等价于 logaddr 0x83
```

- 参数：`logaddr <sid> [area]`；`sid` 是 u16，`area` 是 u32。
- 传输：UIPC ID **0x8f013a**（同步）。请求 payload：
  `+0 u16 type=0xb`、`+2 u16 sid`、`+4 u32 area`；
  回复 payload：`+8 u32 size`、`+0xc u32 address`。
- 返回值是 **PA**；`size` 是**整块**（含 36 字节头）。
- 数据起点 = 返回地址 **+36**；可读长度 = 返回 size **−36**。
- 内核端 `ulogio_get_logaddr`（`.ko:0x1a4c`）：
  - `sid=0`：返回 cfg 指针（日志缓冲基址）+ `cfg[+0x38]+60`；
  - `area=-1`：返回**描述符地址** + `total_size`（SID 0x83 即
    `0x0308503c` / `0x00080340`）；
  - `area>=0`：返回 `area[area].base` + `area[area].size`（SA0 即
    `0x030850d8` / `0x00001024`）。
- SID 不存在、或 `area` 不在 `[-1, count)` 时，内核返回失败，
  CLI 打印 ` failed to get log address(%x).`（`size==0` 也会失败）。
  这是整套命令里**唯一**存在范围校验的地方。

可在设备上先跑：

```
logaddr 0
# 预期：log address: 0x03085000
#       log size: 0x47803c bytes   （0x478000 + 60）
```

如果地址不是 `0x03085000`，说明运行期从备份恢复过，后续一律以
`logaddr` 的输出为准，本文的 PA 只对“按配置新建”的 2.00 成立。

### 4.4 109 个 SID 汇总（2.00，PA）

“区域字节”是整块（每个区域含 36 B RBUF 头）；实际数据 = 该值减去
`36 * SA 数`。逐 SA 的 base/data/end 见 `sid_table_200.tsv`。
2.03 见 `sid_table_203.tsv`（110 个 SID、419 个区域）。

| SID | SA 数 | 区域总字节（含头） | 首区域 base | 末区域 end |
|-----|------:|---------:|-------------|------------|
| 0x0083 | 17 | 0x802a4 | 0x030850d8 | 0x0310537c |
| 0x0080 | 3 | 0x40ac | 0x031053a8 | 0x03109454 |
| 0x0081 | 3 | 0x40ac | 0x03109480 | 0x0310d52c |
| 0x007f | 3 | 0x40ac | 0x0310d558 | 0x03111604 |
| 0x0029 | 3 | 0x40ac | 0x03111630 | 0x031156dc |
| 0x002a | 3 | 0x40ac | 0x03115708 | 0x031197b4 |
| 0x002b | 3 | 0x40ac | 0x031197e0 | 0x0311d88c |
| 0x002c | 3 | 0x40ac | 0x0311d8b8 | 0x03121964 |
| 0x002d | 3 | 0x40ac | 0x03121990 | 0x03125a3c |
| 0x0053 | 3 | 0x40ac | 0x03125a68 | 0x03129b14 |
| 0x0054 | 3 | 0x40ac | 0x03129b40 | 0x0312dbec |
| 0x0055 | 8 | 0x18160 | 0x0312dc40 | 0x03145da0 |
| 0x0063 | 3 | 0x40ac | 0x03145dcc | 0x03149e78 |
| 0x0026 | 4 | 0xc0d0 | 0x03149eac | 0x03155f7c |
| 0x0002 | 3 | 0x1d0ac | 0x03155fa8 | 0x03173054 |
| 0x0003 | 11 | 0xb684c | 0x031730c0 | 0x0322990c |
| 0x0006 | 9 | 0x8184 | 0x03229968 | 0x03231aec |
| 0x0056 | 4 | 0x40d0 | 0x03231b20 | 0x03235bf0 |
| 0x0065 | 4 | 0x40d0 | 0x03235c24 | 0x03239cf4 |
| 0x0064 | 3 | 0x40ac | 0x03239d20 | 0x0323ddcc |
| 0x0059 | 2 | 0x8088 | 0x0323ddf0 | 0x03245e78 |
| 0x005a | 2 | 0x8088 | 0x03245e9c | 0x0324df24 |
| 0x0058 | 2 | 0x8088 | 0x0324df48 | 0x03255fd0 |
| 0x0069 | 4 | 0x30d0 | 0x03256004 | 0x032590d4 |
| 0x005e | 2 | 0x1088 | 0x032590f8 | 0x0325a180 |
| 0x005f | 2 | 0x1088 | 0x0325a1a4 | 0x0325b22c |
| 0x0067 | 2 | 0x888 | 0x0325b250 | 0x0325bad8 |
| 0x00d1 | 3 | 0x46c | 0x0325bb04 | 0x0325bf70 |
| 0x0057 | 9 | 0x61184 | 0x0325bfcc | 0x032bd150 |
| 0x0068 | 9 | 0x4e104 | 0x032bd1ac | 0x0330b2b0 |
| 0x006b | 2 | 0x4088 | 0x0330b2d4 | 0x0330f35c |
| 0x006c | 2 | 0x1088 | 0x0330f380 | 0x03310408 |
| 0x007a | 3 | 0x3c0ac | 0x03310434 | 0x0334c4e0 |
| 0x0097 | 3 | 0x400ac | 0x0334c50c | 0x0338c5b8 |
| 0x003c | 2 | 0x40088 | 0x0338c5dc | 0x033cc664 |
| 0x00c5 | 14 | 0x18238 | 0x033cc6e8 | 0x033e4920 |
| 0x0066 | 17 | 0x45a4 | 0x033e49bc | 0x033e8f60 |
| 0x0093 | 7 | 0x353c | 0x033e8fac | 0x033ec4e8 |
| 0x00bd | 3 | 0x8ac | 0x033ec514 | 0x033ecdc0 |
| 0x007b | 2 | 0xc88 | 0x033ecde4 | 0x033eda6c |
| 0x007c | 2 | 0xc88 | 0x033eda90 | 0x033ee718 |
| 0x007d | 2 | 0xc88 | 0x033ee73c | 0x033ef3c4 |
| 0x011b | 2 | 0xc88 | 0x033ef3e8 | 0x033f0070 |
| 0x007e | 2 | 0x1088 | 0x033f0094 | 0x033f111c |
| 0x0061 | 3 | 0x140ac | 0x033f1148 | 0x034051f4 |
| 0x00ca | 2 | 0x10088 | 0x03405218 | 0x034152a0 |
| 0x0036 | 2 | 0x888 | 0x034152c4 | 0x03415b4c |
| 0x00e1 | 2 | 0x2088 | 0x03415b70 | 0x03417bf8 |
| 0x00b3 | 2 | 0x3088 | 0x03417c1c | 0x0341aca4 |
| 0x0035 | 3 | 0x40ac | 0x0341acd0 | 0x0341ed7c |
| 0x009a | 6 | 0x1918 | 0x0341edc0 | 0x034206d8 |
| 0x009b | 6 | 0x918 | 0x0342071c | 0x03421034 |
| 0x009c | 6 | 0x1918 | 0x03421078 | 0x03422990 |
| 0x009d | 6 | 0x918 | 0x034229d4 | 0x034232ec |
| 0x00a0 | 3 | 0x10ac | 0x03423318 | 0x034243c4 |
| 0x00a1 | 3 | 0x40ac | 0x034243f0 | 0x0342849c |
| 0x00a2 | 2 | 0x2088 | 0x034284c0 | 0x0342a548 |
| 0x0104 | 2 | 0x1088 | 0x0342a56c | 0x0342b5f4 |
| 0x003d | 2 | 0x4088 | 0x0342b618 | 0x0342f6a0 |
| 0x003e | 2 | 0x3c88 | 0x0342f6c4 | 0x0343334c |
| 0x00d9 | 3 | 0x10ac | 0x03433378 | 0x03434424 |
| 0x00d6 | 4 | 0x30d0 | 0x03434458 | 0x03437528 |
| 0x00c4 | 3 | 0x20ac | 0x03437554 | 0x03439600 |
| 0x010a | 2 | 0x488 | 0x03439624 | 0x03439aac |
| 0x00c0 | 2 | 0x488 | 0x03439ad0 | 0x03439f58 |
| 0x00bf | 2 | 0x3088 | 0x03439f7c | 0x0343d004 |
| 0x0106 | 2 | 0x488 | 0x0343d028 | 0x0343d4b0 |
| 0x0101 | 6 | 0x1b18 | 0x0343d4f4 | 0x0343f00c |
| 0x0052 | 2 | 0x1088 | 0x0343f030 | 0x034400b8 |
| 0x0045 | 2 | 0x1088 | 0x034400dc | 0x03441164 |
| 0x0015 | 7 | 0x263c | 0x034411b0 | 0x034437ec |
| 0x0092 | 14 | 0x41f8 | 0x03443870 | 0x03447a68 |
| 0x00be | 13 | 0x1a14 | 0x03447ae4 | 0x034494f8 |
| 0x0138 | 2 | 0x1a48 | 0x0344951c | 0x0344af64 |
| 0x0136 | 2 | 0x1088 | 0x0344af88 | 0x0344c010 |
| 0x0041 | 1 | 0x424 | 0x0344c02c | 0x0344c450 |
| 0x0170 | 4 | 0x7090 | 0x0344c484 | 0x03453514 |
| 0x016c | 1 | 0x824 | 0x03453530 | 0x03453d54 |
| 0x00c2 | 2 | 0x488 | 0x03453d78 | 0x03454200 |
| 0x016e | 3 | 0x40ac | 0x0345422c | 0x034582d8 |
| 0x005d | 2 | 0x888 | 0x034582fc | 0x03458b84 |
| 0x016f | 2 | 0x488 | 0x03458ba8 | 0x03459030 |
| 0x0137 | 3 | 0x6ac | 0x0345905c | 0x03459708 |
| 0x0159 | 1 | 0xc24 | 0x03459724 | 0x0345a348 |
| 0x015a | 1 | 0x2024 | 0x0345a364 | 0x0345c388 |
| 0x00a5 | 2 | 0x448 | 0x0345c3ac | 0x0345c7f4 |
| 0x013f | 2 | 0x4088 | 0x0345c818 | 0x034608a0 |
| 0x0141 | 2 | 0x4088 | 0x034608c4 | 0x0346494c |
| 0x013e | 2 | 0x4088 | 0x03464970 | 0x034689f8 |
| 0x0150 | 3 | 0x40ac | 0x03468a24 | 0x0346cad0 |
| 0x0154 | 3 | 0x100ec | 0x0346cafc | 0x0347cbe8 |
| 0x0167 | 2 | 0x4088 | 0x0347cc0c | 0x03480c94 |
| 0x0181 | 3 | 0x14ec | 0x03480cc0 | 0x034821ac |
| 0x0028 | 8 | 0x2220 | 0x03482200 | 0x03484420 |
| 0x018a | 2 | 0x288 | 0x03484444 | 0x034846cc |
| 0x0189 | 2 | 0x1088 | 0x034846f0 | 0x03485778 |
| 0x018c | 2 | 0x1088 | 0x0348579c | 0x03486824 |
| 0x0125 | 4 | 0x18090 | 0x03486858 | 0x0349e8e8 |
| 0x0196 | 5 | 0x4d8 | 0x0349e924 | 0x0349edfc |
| 0x000d | 2 | 0x3848 | 0x0349ee20 | 0x034a2668 |
| 0x0004 | 1 | 0x2824 | 0x034a2684 | 0x034a4ea8 |
| 0x019e | 2 | 0x9048 | 0x034a4ecc | 0x034adf14 |
| 0x01af | 2 | 0x4088 | 0x034adf38 | 0x034b1fc0 |
| 0x0070 | 2 | 0x888 | 0x034b1fe4 | 0x034b286c |
| 0x025e | 3 | 0x40ac | 0x034b2898 | 0x034b6944 |
| 0x0233 | 2 | 0x1048 | 0x034b6968 | 0x034b79b0 |
| 0x0222 | 2 | 0x1048 | 0x034b79d4 | 0x034b8a1c |
| 0x00ff | 24 | 0x660 | 0x034b8af0 | 0x034b9150 |
| 0x00bc | 1 | 0x4024 | 0x034b916c | 0x034bd190 |

### 4.5 SID 0x83 的 17 个 SA（完整示例，PA）

| SA | 整块 size | base（RBUF 头） | data（base+36） | end |
|---:|---:|---|---|---|
| 0 | 0x00001024 | 0x030850d8 | 0x030850fc | 0x030860fc |
| 1 | 0x00003024 | 0x030860fc | 0x03086120 | 0x03089120 |
| 2 | 0x00002824 | 0x03089120 | 0x03089144 | 0x0308b944 |
| 3 | 0x00004024 | 0x0308b944 | 0x0308b968 | 0x0308f968 |
| 4 | 0x00029024 | 0x0308f968 | 0x0308f98c | 0x030b898c |
| 5 | 0x00003024 | 0x030b898c | 0x030b89b0 | 0x030bb9b0 |
| 6 | 0x00001824 | 0x030bb9b0 | 0x030bb9d4 | 0x030bd1d4 |
| 7 | 0x00007824 | 0x030bd1d4 | 0x030bd1f8 | 0x030c49f8 |
| 8 | 0x0000c024 | 0x030c49f8 | 0x030c4a1c | 0x030d0a1c |
| 9 | 0x00002024 | 0x030d0a1c | 0x030d0a40 | 0x030d2a40 |
| 10 | 0x00010824 | 0x030d2a40 | 0x030d2a64 | 0x030e3264 |
| 11 | 0x00005024 | 0x030e3264 | 0x030e3288 | 0x030e8288 |
| 12 | 0x0000c024 | 0x030e8288 | 0x030e82ac | 0x030f42ac |
| 13 | 0x00003024 | 0x030f42ac | 0x030f42d0 | 0x030f72d0 |
| 14 | 0x0000c024 | 0x030f72d0 | 0x030f72f4 | 0x031032f4 |
| 15 | 0x00000064 | 0x031032f4 | 0x03103318 | 0x03103358 |
| 16 | 0x00002024 | 0x03103358 | 0x0310337c | 0x0310537c |

SA15/SA16 在配置里带 bit31（flag），`flag_count=2`；flag 的语义未确认
（§8），但分配/地址与普通区域一致。

---

## 5. `dk` 与 `mu` 的文件行为

### 5.1 `dk`（内存 → 文件）

```
open(path, O_RDWR|O_CREAT|O_TRUNC|O_APPEND, 0644)
write(fd, mapped, size)     # size = 用户给的字节数
munmap(); close(fd)
```

- 路径：**任意**，直接用参数，不限制目录、不检查 `..`。
  唯一的实际限制是主循环用 `fgets(buf, 0x80)` 读整行，
  所以路径最多约 120 字符（没有单独的路径长度校验）。
- 权限：`0644`；能创建/截断 root 可写路径。
- 大小：**无上限**；`size` 是 32 位，实际受 `mmap`/物理窗口限制。
- `write` 的返回值没有检查，磁盘满时会静默截断。
- 如果 `size` 跨进无效 PA，会在读/写文件之前或中途挂死。
- 推荐小步：先 `dk` 4 KB，确认文件内容后再扩大。

示例（SID 0x83 SA0 的实际数据）：

```
dk 0x030850fc 0x1000 /tmp/sid83_sa0.bin
```

### 5.2 `mu`（文件 → 内存）

```
open(path, O_RDONLY)
lseek(fd, 0, SEEK_END) → filesize
len = min(size, filesize)
mmap(file, len, PROT_READ, MAP_SHARED, fd, 0)
mmap(/dev/mem, len+off, PROT_READ|PROT_WRITE, MAP_SHARED, memfd, pagebase)
memcpy(dest, src, len)
```

- 源路径任意可读；目标长度自动夹到文件大小。
- 不会越过文件末尾，但**会**越过物理窗口（如果目标 PA + len 无效）。
- 写前务必 `dk` 备份同一段 PA。

---

## 6. `switch` 子菜单

`ulogio.elf:0xa1c0`：

1. `switch <sid>`：通过 UIPC ID **0x8f0139** 发同步请求，payload
   前 2 字节是 opcode **0x800d**，后面带 SID；`switch`（无参数）：
   opcode **0x800e**（语义未确认）。
2. 回复的前 `0x8c` 字节存到全局 `0x1454c`：
   - `+0x00` u16：非 0 表示进入菜单（此时提示符用 `[%3x]>` 打印这个 id）；
   - `+0x04` u32：子系统服务 ID（转发目标）；
   - `+0x0a`：子系统名字符串；非空时提示符是 `[名字]>`。
3. 菜单循环：
   - `fgets(0x80)` 读一行；
   - 前 5 个字符与 `"uquit"` 忽略大小写比较 → 本地退出回主提示符；
   - 否则去掉换行后，**把整行原样**通过 UIPC 消息 ID **0x8f0139**
     发给 `+0x04` 指向的子系统（`.elf:0x9afc`），`usleep(100000)`。
   - `fgets` 返回 0（Ctrl-D/EOF）→ 直接 `exit()`，整个 CLI 退出。

**所以子菜单不是本地命令解释器**，没有 `db/dw`；命令集完全由子系统决定。
现有三个文件里没有子系统侧的实现，无法枚举。
反过来，**`db/dw/dl/dk/mb/...` 不需要先 `switch`**：它们在主菜单的
命令表里，直接可用；`switch` 只改变之后输入行的转发目的地。

相关命令（`help` 里可见的原始说明；UIPC ID 都是 **0x8f0139**）：

| 命令 | 处理函数 | payload opcode | 原始 help |
|---|---|---|---|
| `ilist` | `0xa19c` | 0x800c | `ilist -- list subsystem with menu` |
| `tlist` | `0xa16c` | 0x800f | `tlist -- list terminals` |
| `ot` | `0xa140` | 0x8010 | `ot -- set output terminal by index` |
| `it` | `0xa140` | 0x8011 | `it -- set input terminal` |

这四个都只发请求（async，不等回复），CLI 不解析/打印回复；
`ilist` 的“列子系统”输出（如果有）在服务侧，不在这个二进制里。
`switch` 和 `logaddr` 才是同步请求（sync）。

主菜单还有这些命令（`help` 原文见命令表 `0x141e0`）：
`alog`、`filter`、`trace_filter`、`lsnap`、`lstart`、`lstop`、
`rewind`、`term`、`efree`、`uipc`、`uipctxt`、`help`、`exit`、
`crash`、`timetag`、`telnet`。其中：

- `crash -- trigger exception handler`：**主动触发异常，不要试**。
- `uipc/uipctxt`：直接发任意 UIPC 消息，能碰到的东西比 `db/ml` 更广，
  也更危险。
- `lstart/lsnap/lstop` 是日志抓取（`lstart <SubSystemID> <filename>`），
  与 §4 的 SID 对应，可用来把某一路日志导成文件。

这些命令都只在**主菜单**里；`switch` 之后仍然是远端解释，结论不变。

---

## 7. 上机安全步骤（只读）

先做“最小验证”，确认 `/dev/mem` 策略和地址模型都对，再扩大范围：

```
# 1) 确认日志缓冲基址/大小（这是内核归一化后的 PA）
logaddr 0
#   预期 log address: 0x03085000
#   预期 log size:    0x47803c bytes

# 2) 确认第一个描述符（12 字节 = 3 个 dword）
dl 0x0308503c 12
#   预期 53425553 00000083 00080340

# 3) 确认 count / flag_count（各读 2 字节）
dw 0x0308504a 2      # 0011
dw 0x0308504c 2      # 0002

# 4) 确认 SA0 的表项（8 字节 = size + base-KVA）
dl 0x03085050 8
#   预期 00001024 630850D8

# 5) 确认 RBUF 头（36 字节）
dl 0x030850d8 36
#   预期 46554252 630850FC 00001000 00000FFF 630850FC 630850FC 630850FC 00000000 00000000

# 6) 用 logaddr 交叉验证一个区域
logaddr 0x83 0
#   预期 address 0x030850d8，size 0x1024
```

如果第 2 步打不开 `/dev/mem`、mmap 失败或返回全 0，说明内核
`CONFIG_STRICT_DEVMEM` 可能开着（§8），先别继续。

然后按需读取（示例：读 SID 0x83 SA0 的实际数据）：

```
db 0x030850fc 0x1000          # 文本/十六进制
dl 0x030850fc 0x1000          # 32 位字
dk 0x030850fc 0x1000 /tmp/sa0.bin
```

**不要做的事：**

- 不要 `dl 0x635c6000 ...`（§1.3）。
- 不要读/写 `0x40000000–0x7FFFFFFF`。
- 不要跨区域边界读大块；尤其不要把“日志区 + 保留区 + 空洞”一次读完。
- 不要在 `0x15800000–0x40000000`、DDR1、MMIO 上写任何东西。
- 不要写描述符/RBUF 头（`0x0308503c–0x030850d8`、每个 base 的前 36 字节）。
- `dk` 先小后大；先备份再 `mb/mw/ml/mf/mu`。

如果已经挂死：telnet 会话多半直接断；能否恢复取决于总线是否锁死，
没有软件补救手段，只能断电重启。

---

## 8. 未确认 / 分不清的

1. **`CONFIG_STRICT_DEVMEM`**：现有材料（`/usr` 分区）没有内核 `.config`。
   如果开着，`/dev/mem` 对 System RAM 的访问会被限制；§7 第 2 步可以
   实测。MMIO 区域即使开着也可能仍可访问（更危险）。
2. **`switch` 后子系统的命令集**：实现不在 `ulogio.elf` /
   `libosal_ulogio.so` / `osal_ulogio.ko` 里，无法从代码枚举。
   只能上机试；`uquit` 是唯一确定的本地命令。
3. **`switch` 无参数（0x800e）的语义**：代码路径与 `0x800d` 共用，
   推测是“恢复/查询当前子系统”，未验证。
4. **`ilist`/`tlist`/`ot`/`it` 的可见输出**：CLI 只发请求，不解析回复；
   列表是否打印在 telnet 上、还是只进内核日志，未确认。
5. **区域 size 的 bit31（flag）语义**：只影响 `flag_count` 计数，
   分配和地址计算与普通区域相同；具体含义（是否“共享/不清空/持久”）
   未确认。
6. **描述符 `+0x0c` 的 u16**：`ulogio_lbm_init` 没有写这 2 字节
   （只写 +0x0e 的 count、+0x10 的 flag_count、+0x12 的 0）；
   正常路径下通常为 0，但不能保证（日志缓冲未必清零）。所以 §4.2 没有把
   `0x0308503c` 的第 4 个 dword 写成固定值。
7. **`UCPA` 配置标记**：模块在 `cfg[+4] == 0x41504355 ("UCPA")` 时会
   跳过 flag 计数和 RBUF 头初始化，改为信任预置区域。2.00 的配置里
   **没有** `UCPA`（原始字节 0 次），所以走正常初始化路径；其他机型/
   固件是否使用未确认。
8. **`0x635C6000` 的 DSP 物理背面**：ARM 线性映射给出 `0x035C6000`，
   且该 PA 在保留 RAM 内；但 DSP 可能有自己的 MMU/重映射，不能证明
   DSP 的 `0x635C6000` 就落在 `0x035C6000`。不要用 `/dev/mem` 去验证。
9. **DDR1 / 680 MB 保留区的实际可用性**：物理上存在，但主系统把它们
   标成 `:uc` 保留；读可能成功，数据可能正在被 DMA 改写。不建议依赖。
10. **运行期日志缓冲基址**：如果模块从备份恢复（`Recover Flag`），
    `LOGB.base` 可能不是 `0x03085000`；以 `logaddr 0` 为准。
11. **旧笔记的 110 SUBS**：`ulogio-format.md` 写 110，实际 2.00 是
    **109**（原始 `SUBS` 字节出现 109 次，全部解析成功）；已在 §4.1 更正。

---

## 9. 文件与复现

本目录：

| 文件 | 用途 |
|---|---|
| `sid_table.py` | 回放 `ulogio_lbm_init`，从 `ULOGIO_BIN` 生成 SID/SA → PA 表 |
| `sid_table_200.tsv` | 2.00 全表：3 行注释 + 表头 + 417 行，列 `stat/sid/sid_dec/area/size/base/data/end/note` |
| `sid_table_203.tsv` | 2.03 全表：3 行注释 + 表头 + 419 行，列同上 |
| `find_refs.py` | 早期查引用的小脚本（PIC/表引用不完整，未用于结论） |
| `README.md` | 本文 |

复现：

```
python3 sid_table.py ../a7c-shared/setting/ULOGIO_BIN     --tsv > sid_table_200.tsv
python3 sid_table.py ../a7c-shared/setting/ULOGIO_203.BIN --tsv > sid_table_203.tsv
# 不带参数时默认读 a7c-shared/setting/ULOGIO_BIN
```

`sid_table.py` 的假设（都已在 `.ko` 反汇编里核对）：

- `cfg` 是日志缓冲开头的 60 字节头；arena 从 `cfg+60` 开始；
- `cfg[+0x08]` = 日志缓冲地址，`cfg[+0x38]` = 缓冲大小；
- 区域分配循环、`sub_end` 夹取、4 字节对齐、`size=0 → base=0`
  与模块逐指令一致；
- 模块在运行时往区域表里写的是 **KVA**（DDR0 为 PA+0x60000000，
  DDR1 为 PA+0x20000000）；脚本**不读这些 KVA**，而是从 config 的
  `LOGB.base`（PA `0x03085000`）开始回放分配循环，直接算 PA。
  两种结果可用 §7 的 `logaddr` / `dl 0x030850d8` 交叉验证。

反汇编工具：`/Users/wubin/a7c-tasks/telnet-console/dis_arm.py`
（Capstone，Thumb-2）；`.ko` 的完整 ARM 反汇编在 `/tmp/ko_dis.txt`
（临时文件，重跑需重新生成）。三个二进制来自
`/Users/wubin/a7c-tasks/telnet-console/extracted/`：
`osal_ulogio.ko`（38,988 B）、`libosal_ulogio.so`（31,132 B）、
`ulogio.elf`（19,152 B）。
