# R16-C: UUD 条件（版本门）——已从 libsdfileinputupdaterapi.so 反汇编钉死

载体：`r15/tree/usr/lib/libsdfileinputupdaterapi.so`（含 SDUUDConditionChecker 全部成员，
UdrAPI 日志前缀也出自它）。arm-linux-gnueabi-objdump。

## isVersionOK @0xd46c（firmware_information_t：old=+4/+8，new=+28/+32）
```
ldr r2,[r1,#28] ; ldr r3,[r1,#4] ; cmp r2,r3
  bcc -> return 0            ; new.major <  old.major  => FAIL
  bne -> return 1            ; new.major >  old.major  => OK
 相等时: ldr r0,[r1,#32] ; ldr r3,[r1,#8] ; cmp r0,r3 ; ite ls -> ls:0 hi:1
                            ; new.minor >  old.minor  => OK，否则 FAIL
```
⇒ **版本门 = 严格大于（major 大，或 major 相等且 minor 大）；同版/降级必挂**（p5 实测 Error 86 吻合；
真机 Error 72 "Current software version is newer" 同族）。
isModelOK @0xd490 = [r1,#36]!=[r1,#12] 的归一化（1=不同）；isRegionOK @0xd4a2 同理（+40 vs +16）。

## Old/New 两份 firmware_information_t 的来源（getFirmwareInformation @0xd4c8）
- Old ← `SDFileInputBodyLoaderModule::GetCurrentFirmwareInfo`（**相机侧**，经 BodyLoader/Backup，不是卡也不是 .dat）；
- New ← vtable+40（getUpdateFirmwareInfo @0xd560）：**FsysFileHandler::Open(路径=SD 上的 .dat) → Seek → Read**
  从 `.dat` 里读一个小结构（走 Fsys ⇒ 我们桩可见的 Open/Seek/Read）——**New 版本号来自 .dat 文件本身**；
- 53/54 行的 printf 参数 = struct 的 +4,+8,+12,+16（Old）与 +28,+32,+36,+40（New）——Model 两边同值(0x91030019)
  是因为相机侧 Model 由 Old 结构给出、New 的 Model 字段也写死同一机型（.dat UDID 记录是 19 对 (modelID,ver≤2) 白名单，
  model 形如 0x4C05xxxx，与 0x91030019 不同域）。
- a2(`/setting`) 根目录实测（挂 offset=0x820000）：无 `sdupdate` 文件（round16 前状态），`/setting/sdupdate` 串更可能是
  运行时创建的状态文件而非判定输入。

## 一句话结论
**同版自制包过不了 mode5 的 UUD 门**：isVersionOK 要求 (New.major,New.minor) 严格大于相机当前 (2,0)；
自制包必须把 .dat 里 New 版本字段做成 ≥2.1（如 2.04→(2,4)? 视字段编码，2.3 显示为 2.3 即 minor=3），
Model/Region 保持 0x91030019/0x0000 才能进门。
