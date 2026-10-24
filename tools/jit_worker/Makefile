# 交叉编译给 A7C 一代（ARM32/Thumb, ARMv7-A, 小端, softfp）。
#
# 本机（macOS）只有 Apple ld，不认 GNU 选项（-EL/--hash-style/--eh-frame-hdr/-shared/-soname），
# 只能编不能链。真正的链接用 OrbStack/Docker 的 arm32v7 容器（M 芯片上原生跑 arm/v7）：
#   make docker     # 在 alpine:3.19 (linux/arm/v7) 里 gcc -shared -nostdlib，产物 libJit.so 落在本目录
#   make test       # 在同一容器里跑 selftest：dlopen + 调 4 个入口 + 检查 cmd.txt 被执行
#
# 产物要求（已实测满足）：ELF 32-bit LSB shared object, ARM, EABI5；
#   python3 ../../tools/jiritsu_pack.py --check-so libJit.so 必须返回 0；
#   未定义符号只能是 POSIX 那几个（fopen/fclose/fputs/fgetc/fwrite/snprintf/strcmp/system），
#   因为相机用户态是 glibc（rootfs busybox 的 interpreter 是 /lib/ld-linux.so.3），
#   dlopen 时这些符号由进程里已加载的 glibc 解析。--hash-style=gnu 没问题：相机的 .so 本身就带 .gnu.hash。
CC      ?= clang
TARGET  ?= armv7-unknown-linux-gnueabi
CFLAGS  := -target $(TARGET) -march=armv7-a -mthumb -mfpu=vfpv3-d16 -mfloat-abi=softfp \
           -O2 -fPIC -shared -nostdlib -Wall -Wl,-soname,libJit.so
IMG     := alpine:3.19
OUT     := libJit.so
# 相机自己的对照库（用于 readelf -A 属性对比）
CAMLIB  := ../../firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libJiritsu.so

.PHONY: all obj docker test attr clean
all: $(OUT)

# 只编不链（本机可行，用来验证源码能过 ARM 编译器）
obj: libJit.o
libJit.o: libJit.c
	$(CC) $(CFLAGS) -c -o $@ $<

# 真链接：arm32v7 容器里的 gcc/GNU ld
docker: libJit.c
	docker run --rm --platform linux/arm/v7 -v "$$PWD":/w -w /w $(IMG) sh -c \
	  'apk add --no-cache gcc musl-dev binutils file >/dev/null 2>&1; \
	   gcc -march=armv7-a -mthumb -mfpu=vfpv3-d16 -mfloat-abi=softfp -O2 -fPIC -shared -nostdlib -Wall \
	       -Wl,-soname,libJit.so -Wl,--hash-style=gnu -Wl,--eh-frame-hdr -o $(OUT) libJit.c; \
	   file $(OUT); nm -D $(OUT) | grep U || true'

# 功能自测：在 arm32 容器里 dlopen 我们的 .so，按 jit_thread 的调用顺序走一遍
test: docker
	docker run --rm --platform linux/arm/v7 -v "$$PWD":/w -w /w $(IMG) sh -c \
	  'apk add --no-cache gcc musl-dev binutils file >/dev/null 2>&1; \
	   mkdir -p /tmp/jiritsu; printf "echo hello-from-worker > /tmp/jiritsu/cmd.log; touch /tmp/jiritsu/cmd.ran\n" > /tmp/jiritsu/cmd.txt; \
	   gcc -O1 -o selftest selftest.c -ldl; ./selftest ./libJit.so; \
	   echo "--- /tmp/jiritsu:"; ls -l /tmp/jiritsu; echo "--- cmd.log:"; cat /tmp/jiritsu/cmd.log 2>/dev/null'

# 属性对比：我们的 .so vs 相机 libJiritsu.so 的 .ARM.attributes（CPU/架构/FP ABI）
attr: $(OUT)
	docker run --rm --platform linux/arm/v7 -v "$$PWD":/w -v "$$PWD/$(CAMLIB)":/cam/libJiritsu.so:ro -w /w $(IMG) sh -c \
	  'apk add --no-cache binutils >/dev/null 2>&1; \
	   echo "=== ours $(OUT) ==="; readelf -A $(OUT); \
	   echo "=== camera /cam/libJiritsu.so ==="; readelf -A /cam/libJiritsu.so'

clean:
	rm -f $(OUT) libJit.o selftest
