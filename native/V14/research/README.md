# V14 reproducibility and research scripts

These scripts record the exact Avatar-specific research process. They were
run against a preserved V9–V12 per-GOP test tree with preprocessed raw frames,
source metadata, decoder binaries and auditable selected-GOP reports.

They are **not** a turnkey encoding front end for arbitrary inputs. The
original lab scripts retain their original research filesystem paths so
experimental results can be traced back to the right test environment.
To reproduce them elsewhere, update `LEGACY`, `HERE`, `ENC` and `PROBE` in
`v13_adaptive_lab.py`, and supply the existing per-GOP source and V12 reports.
The additional V14 scripts expect the 600-trial V13 cache and V13 Quality
decoding already completed in the same working directory.

Tests were performed under Linux using the bundled patched native encoder,
and independently decoded every candidate MOFLEX output. Keyframe-forcing
results were negative and intentionally omitted from the selected releases.

For ordinary user-generated Q plans, use the portable tools in
`../V13/plan_from_raw.py` and `../V14/scene_cut_plan.py` instead.
