import sys
p="/home/wubin/qemu-a7c/qemu-sony/hw/arm/bionz.c"
s=open(p).read()
anchor="#define CXD90045_ATAGS_BASE"
assert anchor in s and "a7c_rst_ops" not in s
add='''
/* ==== r12: in-guest reboot hook ====
 * Kernel (r12 kernel patch) writes any value to PA 0xf240f000 from its
 * arch_reset(); we translate that into a QEMU machine reset request.
 * Run QEMU with -no-reboot to turn that into a clean QEMU exit (code 0x11)
 * so an external supervisor can relaunch with the same (persistent) eMMC
 * image. Deviation: synthetic trigger, not a modeled cxd90045 PMIC/WDT. */
#define A7C_RESET_MAGIC_BASE 0xf240f000
static uint64_t a7c_rst_read(void *opaque, hwaddr addr, unsigned size)
{
    return 0x52535431; /* "RST1" */
}
static void a7c_rst_write(void *opaque, hwaddr addr, uint64_t val, unsigned size)
{
    error_report("R12-RESET-HOOK: guest reset write addr=%" HWADDR_PRIu " val=0x%" PRIx64 " -> SYSTEM_RESET", addr, val);
    qemu_system_reset_request();
}
static const MemoryRegionOps a7c_rst_ops = {
    .read = a7c_rst_read,
    .write = a7c_rst_write,
    .valid.min_access_size = 4,
    .valid.max_access_size = 4,
    .impl.min_access_size = 4,
    .impl.max_access_size = 4,
    .endianness = DEVICE_LITTLE_ENDIAN,
};
'''
s=s.replace(anchor, add+"\n"+anchor,1)
anchor2='''    for (i = 0; i < CXD90045_NUM_HWTIMER; i++) {
        dev = qdev_new("bionz_hwtimer");'''
assert anchor2 in s
ins='''    {
        static MemoryRegion a7c_rst_mmio;
        memory_region_init_io(&a7c_rst_mmio, NULL, &a7c_rst_ops, NULL,
                              "cxd90045-reset-hook", 0x1000);
        memory_region_add_subregion(get_system_memory(), A7C_RESET_MAGIC_BASE, &a7c_rst_mmio);
    }

'''
s=s.replace(anchor2, ins+anchor2,1)
open(p,"w").write(s)
print("bionz.c patched")
