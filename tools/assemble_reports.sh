#!/bin/sh
# Rebuild the two deliverables in /tmp/dis from the intermediate dumps.
# Inputs (produced by tools/linsweep.py, tools/talkdis.py, tools/vtmap.py, r2/rabin2 sweeps):
#   /tmp/dis/crypter_head.txt  hand-written annotated notes for crypter.elf
#   /tmp/dis/crypter_lin.txt   full linear Thumb disassembly of crypter.elf .text
#   /tmp/dis/talk_head.txt     hand-written annotated notes for libupdatertalk.so
#   /tmp/dis/talk_dis.txt      capstone dump of libupdatertalk.so (.init/.plt/.text/.data)
set -e
cd /tmp/dis
{
  cat crypter_head.txt
  echo;  echo "########## APPENDIX A: rabin2 -S (sections) ##########";      cat crypter_sections.txt
  echo;  echo "########## APPENDIX B: PLT stub -> import map ##########";    cat pltmap.txt
  echo;  echo "########## APPENDIX C: rabin2 -i (imports) ##########";       cat crypter_imports.txt
  echo;  echo "########## APPENDIX D: .rodata strings ##########";           cat crypter_strs.txt
  echo;  echo "########## APPENDIX E: vtable map ##########";                cat crypter_vt.txt
  echo;  echo "########## APPENDIX F: FULL LINEAR THUMB DISASSEMBLY of .text 0xab40-0xe790 ##########"
  cat crypter_lin.txt
  echo;  echo "########## APPENDIX G: libupdaterufp.so r2 disassembly (relocs applied, obj.* annotated) ##########"
  sed -n '1,420p' ufp3.txt
} > crypter.txt
{
  cat talk_head.txt
  echo; echo "########## FULL ANNOTATED DUMP of libupdatertalk.so ##########"; cat talk_dis.txt
} > talk.txt
wc -l crypter.txt talk.txt
