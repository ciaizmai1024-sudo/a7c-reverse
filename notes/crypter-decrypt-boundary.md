# 解密入口边界：crypter.elf → Dec_Scramble*（provider = libupdatertalk.so）

> 静态反汇编由 100.122.234.78（2015 MacBook）上 `qoderclicn -m DeepSeek-Flash` 子代理完成（输入是我们已解包的 crypter.elf 三个版本），
> 关键结论由主会话用 `xcrun llvm-nm/llvm-objdump` 独立复核。原始产出：`work/mac-mini-agents/crypter/agent.log` + `out/{200,203,203b}.asm,cg203.json`。

以下分析基于 `crypter-200.elf` / `crypter-203.elf` 的静态反汇编（两版 `.text`/`.rodata` 逐字节相同，地址通用），以及 `crypter-203b.elf` 的对照。没有还原 key 真值。

## 结论

1. **装 key 的位置只有一个边界**：`Dec_ScrambleInit`（libbackup 类库的导入符号）。
   - 200/203：PLT `0xaf54`，GOT `0x1a2a8`，唯一调用点 `0xe6de`
   - 203b：PLT `0xa98c`，GOT `0x19250`，唯一调用点 `0xe0d2`
2. **crypter 没有给这个函数传任何 key 派生输入**。传参只有 `r0 = this+0x58`（1024 字节帧缓冲区指针，正好是 `memset(…,0xff,0x400)` 的返回值），`r1-r3` 已被 memset 破坏，不构成参数。而且该对象此时刚 `new` 出来、还没接上游/容器/文件句柄，**包文件也还没打开**。
3. 每块的 `Dec_Scramble`（200/203 PLT `0xb098`，203b `0xaaa8`）也只收到 `r0 = 16 字节块指针`，一个参数。
4. crypter 的 dynsym 里**只有** `Dec_Scramble` / `Dec_ScrambleInit` 两个相关外部符号；没有 uIPC、RPMB、Backup API；没有 `/dev/mem`；`ioctl` 只出现在 loop 挂载函数里；AES S-box / SHA-256 常量在文件里都不存在。
5. 所以：**从 crypter.elf 边界看，这把 256 位 key 的输入是"零"**。派生逻辑（以及 IV 的来源）完全在提供 `Dec_Scramble*` 的那个 `.so` 内部。它可能走 uIPC Backup 条目 / RPMB / 裸设备窗口，也可能读进程内别的库注册的全局状态，但 crypter 看不到，也无法从包字段推给库。

## 调用链（200/203，地址通用）

数据路径：

```
main F_b1ac
  └─ GetCryptFileInputModeUpdater  F_ba14            (0xb29e)
      └─ Manager ctor F_b9dc  vtable=0xf660          (mode=6)
          └─ Initialize F_b6a0   ← 入口 0xb2b2，mode 参数来自 argv 全局
              ├─ new 0xc   → F_ba78   [this+0x18]
              ├─ new 8     → F_bbf0   [this+0x10]
              ├─ new 0xbc  → F_bb64   [this+0x14]   (MsCryptBufferManager)
              └─ new 0x45c → F_baf4   [this+0x20]   (MsDecryptorModule)
  └─ StartWriting F_bf04  (vtable+0x10)              (入口 0xb2c2)
      └─ 模块泵 F_d2e0 → 调模块 vtable+0x3c
          └─ decryptStream F_e7fc
              ├─ F_e7b0  读 0x400 字节到 this+0x58
              ├─ vtable+0x48 → F_e638  逐 16 字节调 Dec_Scramble
              └─ verifySum F_e738                      (调用点 0xe854)
```

装 key 路径（在 StartWriting 之前就完成）：

```
F_b6a0 Manager::Initialize
  └─ 0xb6ec  bl F_baf4        ; new 0x45c 后立即构造
      └─ 0xbafa bl F_e6bc     ; DecryptorModule ctor
          ├─ 0xe6c2 F_d654    ; base ctor
          ├─ 0xe6d2 vptr = 0x101f8
          ├─ 0xe6d6 this->size = 0
          ├─ 0xe6da memset(this+0x58, 0xff, 0x400)
          └─ 0xe6de blx Dec_ScrambleInit   ← 唯一装 key 边界
      └─ 0xbafe vptr = 0xf828 (MsDecryptorModule)
```

`verifySum` 细节（`F_e738`）：写日志在 `0xe770`，格式串 `0x10278` 即 `UdrAPI,%d,%s:%d,"%d:%d"`，文件行号 `DecryptorModule.cpp:0x70`。第一个数是 `F_e6f4` 对 `this+0x5a` 起 `0x3fe` 字节的 u16 累加（算出的值），第二个数是 `F_e72c` 读 `this+0x58` 的帧头校验和。缓冲区布局：`+0x58` 校验和、`+0x5a` 长度（bit15 末块）、`+0x5c..0x458` 1020 字节负载。

## 203b 地址（你的 `crypter_text_203.asm` / `crypt_syms_*` 是这一版）

| 作用 | 203b |
|---|---|
| Manager::Initialize | `F_b0c8`（new 0x45c @0xb10a，调 ctor @0xb114） |
| MsDecryptorModule ctor | `F_b524`（→ `F_e0b0` @0xb52a） |
| DecryptorModule ctor | `F_e0b0`（Dec_ScrambleInit @0xe0d2） |
| 块变换 | `F_e02c`（Dec_Scramble @0xe07a） |
| 校验和 | `F_e0e8` |
| verifySum | `F_e12c`（日志 @0xe164） |
| decryptStream | `F_e1f0`（块变换 @0xe242，verifySum @0xe248） |
| FDAT 解析 | `F_b2a0`（"found FDAT" 日志 @0xb370） |
| PLT Dec_Scramble / Init | `0xaaa8` / `0xa98c` |

跨版本换算：DecryptorModule 区整体差 `+0x60c`（203b → 200/203），Manager 区差 `+0x5d8`，派生 ctor 差 `+0x5d0`。

## 输入来源核查（都是否定证据）

- **传参**：装 key 时对象还没 `BaseModule::Initialize`、没有 upstream/buffer/回调，也没有文件名（文件名是 `StartWriting` 时作为 `r1` 给 manager 的，见 `0xb2be`）；库拿不到包路径。
- **导入符号**：只有 `Dec_Scramble`、`Dec_ScrambleInit`（UND，未版本化）。DT_NEEDED 里确有 `libbackup.so`、`libosal_uipc.so`、`libosal_utm.so`，但 crypter 没有直接引用其中任何 uIPC/backup 函数。
- **设备访问**：字符串只有 `/dev/mmca`、`/dev/ms`、`/dev/nflasha1/2/10`、`/dev/loop0`；无 `/dev/mem`、无 `rpmb`。`ioctl` 全在 `F_e9a0/F_ea44/...`（loop 挂载）；`lseek` 只有 `0xee2a`、`0xf0ae` 两处，在处理 `/setting`、`/tmp` 的 flag/备份文件，不在解密路径。
- **包字段**：FDAT 解析 `F_b878`（vtable+0x1c，仅当 manager mode==1）只做容器魔数 `89 55 46 55 0d 0a 1a 0a`（`0xf650`）、8 字节块头、"FDAT"（`0xf720`）比对和 `Seek` 跳块，不向解密模块传任何字段。
- **加密实现**：文件内搜不到 AES S-box / rcon / SHA-256 K、H0，进一步说明 AES 与密钥调度在库内。

一个值得注意的旁证：如果 IV 真的取自镜像尾，crypter 这条路径也从未读包尾（只有 FDAT 解析的 `FsysFileHandler::Seek` 跳块），所以 IV 与 key 一样，必须由库自己从外部状态拿。这与"官方包 key vs 运行时 key 不同、且两把都不在 flash 里"的现象一致，**更像设备/服务侧秘密（Backup 条目、RPMB、裸 flash 窗口），而不是包内字段**——但这是推断，定论要在库里看。

## 建议的下一步

1. 找出 `Dec_Scramble*` 的实际提供者（libbackup / libInfraMediaCommon / libMWF 都可能）：
   - 相机上：`LD_DEBUG=bindings ./crypter ... 2>&1 | grep -i scramble`，或 gdb 在 PLT `0xaf54`/`0xb098` 断下后看 `/proc/pid/maps`；也可以对 GOT `0x1a2a8`/`0x1a310`（203b：`0x19250`/`0x192ac`）下观察点。
   - 离线：从 rootfs 取出所有 `.so`，`readelf -sW` 搜 `Dec_Scramble`。
2. 拿到该 `.so` 后看 `Dec_ScrambleInit` 与 `Dec_Scramble` 内部：是否有 `uipc_*`/`open("/dev/…")`/`ioctl`/`mmap`、字符串 `rpmb`、`backup`、`/dev/`。那才是这把 key 的真正输入来源。
3. 如果方便，把提供者 `.so` 放进这个目录，我可以按同样的方式把库内的派生链也拆出来。

工作产物在 `out/203.asm`、`out/203b.asm`、`out/200.asm`、`out/cg203.json`，地址可直接对照。上述结论未涉及 key 的具体取值。

---

## 主会话补充（provider 已定位）

符号名在 a15 分区里出现于 `+0x5f670a`；本地 `xcrun llvm-nm -D` 结果：

```
work/v203/n15/libupdaterufp.so.203 :   U Dec_Scramble / U Dec_ScrambleInit   （也是引用方）
work/v203/a1_initrd/usr/lib/libupdatertalk.so :
    00000648 T Dec_Scramble
    00000620 T Dec_ScrambleInit
    000008830 D KeyArray          ← 提供者就是这只库（整只 3,404 B，Thumb）
```

`KeyArray`（vaddr 0x8830 = file 0x830）实际内容：

```
+0x00  e3 b0 c4 42 98 fc 1c 14 9a fb f4 c8 99 6f b9 24   = SHA256("")前 16 B（离线 KEY_AES，ECB 那把）
+0x10  27 ae 41 e4 64 9b 93 4c a4 95 99 1b 78 52 b8 55   = 第二把 16 B
```

按 Thumb 反汇编（llvm-objdump --triple=thumbv7a）：

```
Dec_ScrambleInit:  r0=[GOT-4+0x20]（外部全局：key 字节缓冲的指针）, r1=0x80(128bit), r2=[GOT-4+0x28](AES_KEY 上下文)
                   → 尾调 AES_set_decrypt_key（key 不在本库内，是别人填好的全局缓冲）
Dec_Scramble(r0=16B 块):  r1=栈上缓冲, r2=[GOT-4+0x28] → AES_decrypt(ECB) → memcpy(r0, 栈, 16)   ← 原地 ECB 解密
UND: AES_decrypt / AES_set_decrypt_key（OPENSSL_1_1_0）、memcpy、__aeabi_unwind_cpp*
```

**已试过的否定结论**（别重复劳动）：`7e68a34d…`(运行时) 与 `c1aa8f7c…`(官方包实际用) 之间
用 `KeyArray[0:16]`、`KeyArray[0x10:0x20]` 做 AES-128-ECB 加/解密（任一半、任方向）**都不匹配**；


**下一步（已下达）**：QEMU 里把 **运行时的 KeyArray**（libupdatertalk.so 加载基址 + 0x8830）、GOT 槽 `0x8814/0x881c`、AES_KEY 上下文整个 dump 出来，跟文件里的比；再扫 guest RAM 看 `7e68a34d…` 从哪冒出来的。
