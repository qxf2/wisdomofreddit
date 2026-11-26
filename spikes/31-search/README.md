# Spike #31: Whoosh vs SQLite FTS5 vs Jammi

Throwaway code for the search spike. The write-up with all numbers and the
recommendation for #29 is on issue #31. Nothing here is used by the app.

Data: the December 2025 stories from `data/comments.db`
(`p_story >= 0.5 AND vividness >= 2`, 34,608 comments).

Machine: 2015 MacBook Air (i5-5250U, 2 cores, 8 GB), data on the USB exFAT
drive. Embedding times are CPU-only; the real build will use a GPU box.

## Layout

- `scripts/` benchmark scripts. They expect a work dir with `venv/` (Python
  3.14, `jammi-ai[embedded]==0.54.0`), `venv311/` (torch 2.2.2 +
  sentence-transformers 3.0.1, the last Intel-Mac torch), `data/` and `idx/`.
  Paths assume `/Volumes/Expansion/code/spike31`.
  - `export.py` stories to Parquet
  - `build_lexical.py` builds FTS5, Whoosh and Jammi BM25, reports time and size
  - `bench_lex.py`, `summ_lex.py` run `random_queries.txt` (warm), latency,
    errors, quoted-phrase precision
  - `encode_full.py` all-MiniLM-L6-v2 vectors at 512 tokens (same vectors as
    Jammi's own encoder, checked by `trunc.py`)
  - `scale_vec.py`, `scale_lex.py`, `slim_probe.py` latency against corpus size
  - `add_month.py` incremental add with `refresh_embeddings`
  - `quality.py` top 10 for 10 queries in five setups
  - `test_wrapper.py` benchmarks the PyO3 wrapper
- `wor_search/` minimal PyO3 + maturin crate over Jammi's Rust
  `LexicalIndex` and `rrf_fuse` (67 lines of Rust). `build.sh` builds it.
- `results/` raw benchmark output, relevance judgments and scores.
