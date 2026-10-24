# a3 (/system, 2.00) — AV-CAM.BIN 解出 + 与 gh#23 (2.03) 跨版本对照

离线分析，仅读 `work/l1_v/nflasha3.bin`（30,290,944 B，md5 `79f0190091d0c64b6810e6d1593f2958`）。
产物：`work/a3-avcam/AV-CAM.BIN`（本目录）。

## 1. BPB 定位与 FAT 参数

**真 BPB 就在 offset 0**，字段自洽（之前看到的 "FATs=512" 是把 root entries 读串了）：

| 字段 | 值 |
|---|---|
| BPB 偏移 | 0x0（`0x55AA`@0x1FE，maker `mkfs.fat`；头 0x10000 内无第二个 boot 签名）|
| bps / spc | 512 / 32（簇 = 16 KiB）|
| reserved / FATs / spf | 1 / 2 / 32 扇区 |
| root entries | 512（根目录 = 扇区 65..128，即 0x8200..0xA1FF；`AV-CAM BIN` 项在 0x8220）|
| 总扇区数 | 59162 × 512 = 30,290,944 B（= dump 大小，精确吻合）|
| FAT 类型 | **FAT12**（数据簇数 (59162−97)/32 = 1845 < 4085；FAT@0x200，12-bit 项，链正常）|
| 数据区起点 | 簇 2 = 扇区 97 = **0xC200**；簇 n 数据 = 0xC200 + (n−2)×0x4000 |

自洽校验：FAT1 与 FAT2 逐字节相同；根目录 14 项（12 文件 + 2 子目录 `LENSBI~1`、`SABIN`），所有簇链都在 0xFFF8..0xFFFF 正常终止。对照 a2 (`/setting`) 不需要——BPB 已在 0 自洽。

## 2. 完整性判定：**dump 不截断（对文件系统而言），md5 可信**

- `partinf.conf` 说 a3 分区 0x3000000 (48 MiB)，但 BPB 声明的**文件系统本身**只有 59162 扇区 = 28.89 MiB = dump 大小。分区尾部 ~19 MiB 在 FAT 卷之外（未用/未知），不影响任何文件。
- AV-CAM.BIN 簇链 3→1064，末簇（1064）完整包含（末簇结束于 dump 内 17,465,856 B << 30,290,944 B），FAT 项 = 0xFF(8..) 终止符。
- 12 个文件全部 size ≤ 簇链容量 且链正常终止 ⇒ **全部完整可读**。

## 3. AV-CAM.BIN（2.00）

```
size   = 17,394,576 B
md5    = 8a3822728974abd4f7704e7f57339d4f
sha256 = 0113bf72420bd0b715821dada13a9cba058e78f2b5d68781dcb298317524d0f9
```
gh#23 的 2.03：17,398,676 B / md5 `440c2a3e77a43c16c2bae5af2f3845c9` ⇒ **不是同一文件**，2.03 比 2.00 大 4,100 B (= 0x1004)。

## 4. ORIL 头（2.00）

在 2.00 文件里 `"ORIL"` 只出现 1 次，**在文件偏移 0x4**（文件最开头，不是 0x28）：

```
00000000: 0a 00 00 ea | 4f 52 49 4c | 04 00 00 00 | 44 60 5c 63
           magic        "ORIL"        version=4      entry VA
```

与 gh#23 给的 2.03 头 16 字节**完全相同**（entry `0x635c6044`）。
⇒ **2.00 的 DSP 平铺基址 = 0x635c6000**（entry − 0x44），与 2.03 及 `liro/parameters/adr=0x635c6000` 一致；文件偏移 = VA − 0x635c6000 在 2.00 同样成立（见下 LUT 对照）。

## 5. LUT 指针表对照（2.00 vs 2.03）

2.00 中结构完全存在，只是整体前移。定位方法：THUMB2 消费函数（文件 `0x550d80` 附近）的字面量池 `0x550dfc..0x550e1c` 里含同一组 profile 结构偏移常量 `0x2c88 / 0x2c24 / 0x4bd0 / 0x70d0 / 0x7e34 / 0x1b5c`；按 "base+0x2c88/+0x4bd0/+0x70d0/+0x7e34 四个 u32 都落在 0x64500000..0x64560000" 扫描全文件，唯一命中。

| 项 | 2.00 | 2.03 (gh#23) | Δ(2.00−2.03) |
|---|---|---|---|
| 表(结构)基址 VA | `0x646519c0`（文件 `0x108b9c0`）| `0x646529c4`（文件 `0x108c9c4`）| −0x1004 |
| +0x2c88 → VA | `0x64543f9e`（文件 `0xF7DF9E`）| `0x64544f9a`（文件 `0xF7EF9A`）| −0xFFC |
| +0x7e34 → VA | `0x645444d2`（文件 `0xF7E4D2`）| `0x645454ce`（文件 `0xF7F4CE`）| −0xFFC |
| +0x4bd0 → VA | `0x64544b72`（文件 `0xF7EB72`）| `0x64545b6e`（文件 `0xF7FB6E`）| −0xFFC |
| +0x70d0 → VA | `0x645452da`（文件 `0xF7F2DA`）| `0x645462d6`（文件 `0xF802D6`）| −0xFFC |

四个 1215 B (405×3) 段在 2.00 **同样全 0**（每段前 16 B = `00×16`，非零字节计数 0/1215）。
⇒ 布局/消费代码两版一致；文件改写后 liro 重载即可，改偏移只需注意 −0xFFC / −0x1004 的版本差。

## 6. a3 其它文件一览（2.00，全部完整）

| 文件 | size | 首簇 | 簇数 | md5 |
|---|---:|---:|---:|---|
| AV-CAM.BIN | 17,394,576 | 3 | 1062 | 8a3822728974abd4f7704e7f57339d4f |
| BONOBO.BIN | 172,144 | 1065 | 11 | 37d65ffefb84423d975e6406d4ac9ae8 |
| BT_FIRM.HCD | 61,787 | 1076 | 4 | be8ac9166791929f152d64d5a637a93b |
| DFE_APP.BIN | 1,956 | 1080 | 1 | 4d6d250734e0ad2e3ffe620de8afdf2b |
| DFE_DAT.BIN | 65,536 | 1081 | 4 | 8c5f3b191dd124cf1ee2cb5055cec37e |
| INITRD.IMG | 2,186,240 | 1085 | 134 | ca8ae5d1ce551ed9794f6772e2561e73 |
| LDR_DRV.BIN | 7,012 | 1219 | 1 | 7c8c16cd1090978558db9a9f4176c006 |
| LIF_APP.BIN | 6,716 | 1231 | 1 | 7f4be40e8dc6afe24f7d0c64ceeb74b5 |
| VMLINUX.BIN | 4,117,632 | 1256 | 252 | a73bf8a79adc71740354b73f69f62815 |
| WOLE_APP.BIN | 10,768 | 1508 | 1 | 265bd0fd0646e86bb91649389abbf362 |

（根目录另有 2 个空子目录：`LENSBI~1`、`SABIN`。）

## 7. 复现命令

```bash
cd /Users/wubin/pi-cwd/sony/a7creverse
python3 - <<'EOF'
import struct,mmap,hashlib,os
f=open('work/l1_v/nflasha3.bin','rb'); m=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
FATOFF,DATA,CS=512,97*512,32*512   # FAT12 @0x200, 簇2=0xC200, 簇=16KiB
def fat(n):
    o=FATOFF+n*3//2; v=struct.unpack('<H',m[o:o+2])[0]; return v>>(4 if n%2 else 0)&0xFFF
def chain(c):
    ch=[c]
    while fat(ch[-1])<0xFF8: ch.append(fat(ch[-1]))
    return ch
# 根目录 @0x8200, AV-CAM 首簇=3 size=17394576（目录项 0x8220: 首簇 u16@+26, size u32@+28）
data=b''.join(m[DATA+(c-2)*CS:DATA+(c-2)*CS+CS] for c in chain(3))[:17394576]
open('work/a3-avcam/AV-CAM.BIN','wb').write(data)
print(len(data),hashlib.md5(data).hexdigest(),hashlib.sha256(data).hexdigest())
# LUT 结构基址（文件偏移）与四表项
B=0x108b9c0
for o in (0x2c88,0x7e34,0x4bd0,0x70d0):
    v=struct.unpack_from('<I',data,B+o)[0]
    blk=data[v-0x635c6000:v-0x635c6000+1215]
    print(hex(B+0x635c6000),'+%#x'%o,hex(v),hex(v-0x635c6000),'allzero',blk==b'\0'*1215)
EOF
```

## 给 gh issue #23 的数据贴文

以下是 ILCE-7C **2.00** 的对照值（我们的 a3 dump：nflasha3.bin，30,290,944 B，md5 `79f0190091d0c64b6810e6d1593f2958`，文件系统 FAT12/VFDA 兼容、未截断）：

| item | 2.00 (us) | 2.03 (yours) | Δ |
|---|---|---|---|
| av-cam.bin size | 17,394,576 B | 17,398,676 B | −4,100 |
| av-cam.bin md5 | `8a3822728974abd4f7704e7f57339d4f` | `440c2a3e77a43c16c2bae5af2f3845c9` | different |
| ORIL header @file off | 0x4 (`0a0000ea ORIL v4 entry 0x635c6044`) — 与 2.03 相同 | same | 0 |
| DSP flat base | `0x635c6000` (same, VA−base==file off holds) | `0x635c6000` | 0 |
| LUT struct base | VA `0x646519c0` / file `0x108b9c0` | `0x646529c4` / `0x108c9c4` | −0x1004 |
| +0x2c88 | VA `0x64543f9e` / file `0xF7DF9E` | `0x64544f9a` / `0xF7EF9A` | −0xFFC |
| +0x7e34 | VA `0x645444d2` / file `0xF7E4D2` | `0x645454ce` / `0xF7F4CE` | −0xFFC |
| +0x4bd0 | VA `0x64544b72` / file `0xF7EB72` | `0x64545b6e` / `0xF7FB6E` | −0xFFC |
| +0x70d0 | VA `0x645452da` / file `0xF7F2DA` | `0x645462d6` / `0xF802D6` | −0xFFC |
| 4× 405×3 B blocks | all zero (0/1215 nonzero each) | all zero | same |
