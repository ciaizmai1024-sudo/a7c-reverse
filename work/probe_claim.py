import sys, os
sys.path.insert(0, 'tools')
import jiritsu_send as J, usb.core, usb.util
print('euid =', os.geteuid())
d = usb.core.find(idVendor=0x054c, idProduct=0x0d29, backend=J.backend())
if d is None:
    print('看不到 054C:0D29'); raise SystemExit
print('kdriver active(0):', d.is_kernel_driver_active(0))
try:
    usb.util.detach_kernel_driver(d, 0); print('detach_kernel_driver(0): OK')
except Exception as e:
    print('detach:', type(e).__name__, e)
try:
    usb.util.claim_interface(d, 0); print('claim iface0: OK ★'); usb.util.release_interface(d, 0)
except Exception as e:
    print('claim:', type(e).__name__, e)
try:
    d.set_altsetting(0, 0); print('set_altsetting: OK')
except Exception as e:
    print('set_altsetting:', type(e).__name__, e)
try:
    n = d.ctrl_transfer(0xC0, 0x00, 0, 0, 8, 2000); print('MSC GET_MAX_LUN:', bytes(n))
except Exception as e:
    print('GET_MAX_LUN:', type(e).__name__, e)
usb.util.dispose_resources(d)
