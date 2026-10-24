#!/usr/bin/env bash
set -u
cd ~/a7c-jiritsu
mkdir -p work/l2 && chmod 777 work/l2
for spec in "nflasha23:300" "nflasha4:600" "nflasha10:600" "nflasha2:900" "nflasha15:3000"; do
  d=${spec%%:*}; t=${spec##*:}
  echo "##### $d start $(date +%T)"
  TMO=$t bash wrap2.sh tools/jiritsu_send.py dump /dev/$d work/l2/$d.bin --twice 2 > work/l2/dump_$d.log 2>&1
  echo "##### $d rc=$? $(date +%T)"; tail -12 work/l2/dump_$d.log
done
echo "##### ALL-DONE"
ls -l work/l2
