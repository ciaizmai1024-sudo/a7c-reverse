> 来源：100.122.234.78（2015 MacBook，macOS 12 x86_64）上 `qoderclicn -m DeepSeek-Flash` 跑出来的子代理产出（2026-10-24），
> 输入是机身 `/setting/ulogio.bin`(2.00, 3,772 B) 与 2.03 包内 `ulogio.bin`(3,796 B)。
> **主会话独立复核通过**：`LOGB base=0x03085000 size=0x00478000`、`PRTB base=0x034FD000 size=0x00008000`（两者首尾相接）、
> `TELN` 标签串在 0x98、值 dword 在 0x94 为 0、`TERM=1`；这两个缓冲**都落在出厂 a1 命令行 `memrsv=0x75e000@0x02E68000` 的保留窗（0x02E68000–0x035C6000）里**，
> 紧挨着 Backup RAM（0x02E80000）⇒ **日志文本一直在保留 RAM 里，不靠控制台也能捞**。
> 脚本已落到 `tools/ulogio_cfg.py`，在机身那份上跑通（128 条顶层 / 130 条含嵌套，往返无损）。

# ulogio `/setting` 文件结构分析

分析对象：

| 文件 | 大小 | 来源 |
|---|---:|---|
| `ulogio-200.bin` | 3772 (0xEBC) | 2.00 机身 `/setting` |
| `ulogio-203.bin` | 3796 (0xED4) | 2.03 官方更新包 |

结论基于两份文件的逐字节解析与“解析 → 重新编码”往返验证：
`ulogio-200.bin` 和 `ulogio-203.bin` 都能无损往返，说明外层 TLV 结构判断正确。

---

## 1. 最外层：没有文件头，整份文件就是记录串

文件没有 magic、版本号、记录数量、文件级长度、校验和或尾部标记。解析器从偏移 0 开始，
按每条记录的长度字段一直读到 EOF；两条样本都恰好读完，没有剩余字节。

每条记录（TLV）的布局：

```text
偏移      类型        说明
+0x00     uint32 LE   total_len
+0x04     char[4]     tag，4 个大写 ASCII 字符，不以 NUL 结尾
+0x08     uint8[]     payload，长度 = total_len - 8
```

关键点：

- **`total_len` 包含它自己的 4 个字节**，也包含 4 字节 tag。
  即 `total_len = 4 + 4 + payload_len`。
- 所有 `total_len` 都是 4 的倍数；payload 也用 `0x00` 补齐到 4 字节边界。
- 最小记录是 8 字节（空 payload）；实际样本里最小是 12 字节。
- 多字节整数均为小端（LE）。

示例，TELN 记录：

```text
0x0094  0c 00 00 00    total_len = 12
0x0098  54 45 4c 4e    "TELN"
0x009c  00 00 00 00    payload = 4 字节
```

### 容器记录

`FBOX` 是唯一发现的容器：它的 payload 不是普通数据，而是**一条或多条完整子记录**。
父记录的长度包含全部子记录，所以天然可以递归解析。

```text
0x00A0  FBOX  total_len=32
        0x00A8  SFLT  total_len=12
        0x00B4  CFLT  total_len=12
        32 = 8 + 12 + 12
```

`SFLT`、`CFLT` 不是顶层段，而是 `FBOX` 的子记录。其他 tag 的 payload 不按记录解析。

---

## 2. 顶层记录表

2.00 与 2.03 在 `0x0000..0x0EBB` 完全一致；2.03 只是在 EOF 追加了一条记录（见第 5 节）。

| 偏移 | 长度 | tag | 说明 / payload |
|---:|---:|---|---|
| `0x0000` | 32 | `LGNM` | 字符串 `191H_Dslr_Astra-Diadem` |
| `0x0020` | 12 | `RECO` | 首字节 `01`，其余保留 |
| `0x002C` | 16 | `LOGB` | 两个 u32：`0x03085000`, `0x00478000` |
| `0x003C` | 16 | `PRTB` | 两个 u32：`0x034FD000`, `0x00008000` |
| `0x004C` | 12 | `CHAN` | 首字节 `00` |
| `0x0058` | 12 | `ISYS` | 首字节 `00` |
| `0x0064` | 12 | `DBGL` | 首字节 `01` |
| `0x0070` | 12 | `DBCL` | `02 06 03 00`，更像 4 个独立字节 |
| `0x007C` | 12 | `FLTA` | 首字节 `00` |
| `0x0088` | 12 | `TERM` | 首字节 `01` |
| `0x0094` | 12 | `TELN` | 首字节 `00`（见第 4 节） |
| `0x00A0` | 32 | `FBOX` | 容器，含 `SFLT` + `CFLT` |
| `0x00A8` | 12 | `SFLT` | FBOX 子记录，首字节 `00` |
| `0x00B4` | 12 | `CFLT` | FBOX 子记录，首字节 `00` |
| `0x00C0` | 28 | `FLTF` | 字符串 `/setting/filter.bin` |
| `0x00DC` | 28 | `RCVF` | 字符串 `/log/escapelog.bin` |
| `0x00F8` | 16 | `ALGP` | 字符串 `/log/`，只是目录前缀 |
| `0x0108` | 24 | `ALGB` | 字符串 `ulogio_blog.dat` |
| `0x0120` | 24 | `ALGD` | 字符串 `ulogio_dlog.dat` |
| `0x0138` | 24 | `ALGK` | 字符串 `ulogio_klog.txt` |
| `0x0150` | 24 | `ALGT` | 字符串 `ulogio_tlog.txt` |
| `0x0168` | 20..112 | `SUBS` | 2.00 共 110 条，2.03 共 111 条 |

`LOGB` / `PRTB` 的两个 u32 很像是“起始偏移 + 长度”：

```text
LOGB: base=0x03085000  size=0x00478000
PRTB: base=0x034FD000  size=0x00008000
0x03085000 + 0x00478000 = 0x034FD000   （正好等于 PRTB 的 base）
```

PRTB 紧接在 LOGB 区域末尾，且长度为 32 KiB，基本可以确定是两块 flash/存储区域描述符。
具体是哪个分区名，仅凭文件无法确认。

---

## 3. 字符串和路径怎么存

字符串记录没有独立的长度字段，直接放在 payload：

```text
payload = ASCII 字符串 + 0x00 终止符 + 若干 0x00 补齐到 4 字节边界
total_len = 8 + 补齐后的 payload 长度
```

实例：

| tag | 字符串 | 字符数 | payload | total_len |
|---|---|---:|---:|---:|
| `LGNM` | `191H_Dslr_Astra-Diadem` | 22 | 22 + 1 + 1 pad = 24 | 32 |
| `ALGP` | `/log/` | 5 | 5 + 1 + 2 pad = 8 | 16 |
| `ALGB` | `ulogio_blog.dat` | 15 | 15 + 1 = 16 | 24 |
| `FLTF` | `/setting/filter.bin` | 19 | 19 + 1 = 20 | 28 |
| `RCVF` | `/log/escapelog.bin` | 18 | 18 + 1 + 1 pad = 20 | 28 |

因此修改字符串时，必须同时更新该记录的 `total_len`，并按 4 字节边界重新补 NUL。
脚本已经自动处理这一点。

### 路径的归属关系

- `FLTF`：自己带完整路径 `/setting/filter.bin`。
- `RCVF`：自己带完整路径 `/log/escapelog.bin`。
- `ALGP`：只存目录前缀 `/log/`。
- `ALGB` / `ALGD` / `ALGK` / `ALGT`：只存裸文件名，运行时与 `ALGP` 拼接。

实际完整路径是：

```text
ALGP + ALGB = /log/ulogio_blog.dat
ALGP + ALGD = /log/ulogio_dlog.dat
ALGP + ALGK = /log/ulogio_klog.txt
ALGP + ALGT = /log/ulogio_tlog.txt
```

注意：**`ALGB` 等并不在文件结构上嵌套在 `ALGP` 下面**，它们是同级顶层记录，
只是语义上共享同一个目录前缀。真正嵌套的只有 `FBOX → SFLT/CFLT`。
同理，`FLTF` 是 `FBOX` 的同级记录，不是 `FBOX` 的子记录。

---

## 4. TELN 的开关字节

`TELN` 记录位置：

```text
记录起点     0x0094  (148)
长度字段     0x0094..0x0097   = 0c 00 00 00
tag          0x0098..0x009B   = 54 45 4C 4E  ("TELN")
payload      0x009C..0x009F   = 00 00 00 00
```

所以：

- 你看到的偏移 **152 (`0x0098`) 是 tag 的第一个字节 `'T'`**，不是值。
- 真正的开关字节是 **文件绝对偏移 156 (`0x009C`)**，是 payload 的第 0 字节。
- 01..03 为保留字节，样本里全为 0。

两份样本的 `TELN` 都是 `00`。同族开关的取值是：

```text
RECO=01  DBGL=01  TERM=01
CHAN=00  ISYS=00  FLTA=00  TELN=00
```

因此按同构关系可以判断 **`0x009C = 0x00` 表示关闭，`0x01` 表示开启**。
需要说明：目前没有 `TELN=1` 的样本，所以“1=开启”是从同族字段推断的，
不是从一份已知开启的文件实测得到的。

脚本修改后只会动这一字节：

```text
$ ./ulogio_cfg.py ulogio-203.bin set TELN on -o telnet-on.bin
set TELN byte 0 at 0x009c to 1
wrote: telnet-on.bin (3796 bytes, ...)
1 byte(s) changed: 0x009c:00->01
```

---

## 5. 2.03 比 2.00 多的 24 字节

逐字节比较结果：**前 3772 字节完全相同**，2.03 仅在文件末尾追加了 24 字节：

```text
0x0EBC  18 00 00 00   total_len = 24
0x0EC0  53 55 42 53   "SUBS"
0x0EC4  a9 00 00 00   SUBS id = 0x000000A9 (169)
0x0EC8  ac 40 00 00   param[0]
0x0ECC  24 40 00 00   param[1]
0x0ED0  64 00 00 80   param[2]
```

即：2.03 新增了一条完整的 SUBS 子参数记录，id 为 `0xA9`，带 3 个 4 字节参数。
它追加在 EOF，因此**没有改动任何已有记录的长度字段或偏移**，文件大小正好 +24。

---

## 6. SUBS 记录内部结构

`SUBS` 是顶层记录，payload 为：

```text
+0x00  uint32 LE   sub_id
+0x04  4 字节条目 × N
```

每条 4 字节条目从样本中表现出一致的布局（**推断**，不是外层 TLV 那种确定结论）：

```text
byte0     类型/字段码
byte1-2   uint16 LE 数值
byte3     标志位，常见 0x80
```

例子，`SUBS id=0x80`：

```text
d8 40 00 00  -> type=0xD8 value=64  flag=0x00
a4 3f 00 00  -> type=0xA4 value=63  flag=0x00
64 00 00 80  -> type=0x64 value=0   flag=0x80
a4 00 00 80  -> type=0xA4 value=0   flag=0x80
```

按这个解释，值都是合理的小整数（64、63、16、48、255、1024 等），
但类型码 `0xD8/0xA4/0x24/0x64...` 的具体含义、以及 flag `0x80` 的语义，
需要固件代码或更多样本才能确认。

这些记录数量很大（2.00 有 110 条），且每条长度 20..112 字节不等，是主要的参数区。
外层的 `SUBS` 长度和边界是确定的；内部条目的语义是推断的。

---

## 7. 脚本：`ulogio_cfg.py`

只依赖 Python 3 标准库。

```text
用法:
  ./ulogio_cfg.py FILE list [--json]
  ./ulogio_cfg.py FILE get TAG [--subs-id ID] [--occurrence N]
  ./ulogio_cfg.py FILE set TAG VALUE [-o OUT | --in-place]
  ./ulogio_cfg.py FILE set-string TAG VALUE [--keep-size] [-o OUT | --in-place]
  ./ulogio_cfg.py FILE set-byte TAG OFFSET VALUE [-o OUT | --in-place]
  ./ulogio_cfg.py FILE set-u32 TAG INDEX VALUE [-o OUT | --in-place]
  ./ulogio_cfg.py FILE patch TAG OFFSET HEXBYTES [-o OUT | --in-place]
  ./ulogio_cfg.py FILE verify
  ./ulogio_cfg.py FILE selftest
```

常用示例：

```bash
# 看全部段
./ulogio_cfg.py ulogio-203.bin list

# 看 TELN 的精确偏移和值
./ulogio_cfg.py ulogio-203.bin get TELN

# 打开 telnet，输出到新文件
./ulogio_cfg.py ulogio-203.bin set TELN on -o telnet-on.bin

# 原地修改（默认会生成 .bak，不覆盖已有 .bak）
./ulogio_cfg.py ulogio-203.bin set TELN on --in-place

# 改日志文件名，长度自动重算
./ulogio_cfg.py ulogio-203.bin set-string ALGT ulogio_tlog2.txt -o out.bin

# 保持记录原大小（适合路径变短、希望后续偏移不变）
./ulogio_cfg.py ulogio-203.bin set-string FLTF /setting/f.bin --keep-size -o out.bin

# 只改 payload 某字节 / 某 u32
./ulogio_cfg.py ulogio-203.bin set-byte TELN 0 1 -o out.bin
./ulogio_cfg.py ulogio-203.bin set-u32 LOGB 1 0x00479000 -o out.bin

# 校验所有长度字段和整文件往返
./ulogio_cfg.py ulogio-203.bin verify
./ulogio_cfg.py ulogio-203.bin selftest
```

安全设计：

- 所有修改都会重新编码记录，**`total_len` 由实际 payload 重新计算**，不手工改长度。
- 字符串变长/变短时，会重算该记录长度；后续记录整体平移；父容器 `FBOX` 的长度也会递归重算。
- 写入前会重新解析新文件并做“解析 → 编码”稳定性检查；写入后再读回校验。
- 不加 `-o` / `--in-place` 时默认只做 dry-run，不落盘。
- `--in-place` 默认生成 `.bak`（已有同名备份时自动用 `.bak.1`、`.bak.2`）。
- `verify` 会逐条比对记录起点处的 `total_len` 与重新编码后的实际大小，包括嵌套子记录。

已验证：

```text
ulogio-200.bin: 128 条顶层记录，130 条含嵌套，3772 字节，往返一致
ulogio-203.bin: 129 条顶层记录，131 条含嵌套，3796 字节，往返一致
```

---

## 8. 结论的确定性与边界

确定（有逐字节往返验证）：

- 记录边界、`total_len` 位置及“长度包含自身”、4 字节对齐。
- tag 为 4 字节 ASCII、无 NUL。
- 字符串为 NUL 终止 + 4 字节补零。
- `FBOX` 的 payload 是子记录序列。
- `TELN` 开关字节在 `0x009C`，不是 `0x0098`。
- 2.03 只在 EOF 追加一条 24 字节的 `SUBS id=0xA9` 记录。

推断（有强证据但未由固件/开启样本证实）：

- `TELN=1` 表示开启；同族开关遵循首字节 0/1。
- `SUBS` 的 4 字节条目为 `[type][u16 LE value][flag]`。
- `LOGB` / `PRTB` 是两块 flash/存储区域的 `base + size` 描述符。

未发现：

- 文件内部没有文件级校验和、签名、记录数量或索引表。
- 不排除设备在上层更新包/刷写流程中另有签名或版本校验。
