#!/bin/sh
cd /Volumes/Expansion/code/spike31
until grep -q "DONE\|Traceback" data/encode.log; do sleep 30; done
grep -q Traceback data/encode.log && { echo "ENCODE FAILED"; exit 1; }
echo "== import real vectors"; venv/bin/python -I scripts/scale_vec.py data/ids_only.parquet data/st512.npy idx/vec_real 2>&1 | grep -v WARN
echo "== lexical bench (uncontended)"
Q=/Volumes/Expansion/code/wisdomofreddit/random_queries.txt
venv/bin/python -I scripts/bench_lex.py fts5 $Q results/lex_fts5.jsonl
/Volumes/Expansion/code/wisdomofreddit/venv/bin/python -I scripts/bench_lex.py whoosh $Q results/lex_whoosh.jsonl
venv/bin/python -I scripts/bench_lex.py jammi $Q results/lex_jammi.jsonl 2>&1 | grep -v WARN
venv/bin/python -I scripts/summ_lex.py
echo "== vector bench"; venv/bin/python -I scripts/bench_vec.py idx/vec_real/db $Q 2>&1 | grep -v WARN
echo "== quality"; venv/bin/python -I scripts/quality.py idx/jammi_lex idx/vec_real/db 2>&1 | grep -v WARN
echo ALL_DONE
