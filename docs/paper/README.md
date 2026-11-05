# arXiv preprint draft

`main.tex` + `references.bib` — "OpenGuide: A Control Plane for LLM Inference
Trajectories". Systems/position paper; the evaluation is **simulated** and says so
in the abstract, Section 5 and Section 6.

## Build

```bash
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

Not yet compiled (no TeX in the authoring environment). Compile and fix any
warnings before submitting. arXiv needs `main.tex`, `references.bib` (or the
generated `main.bbl`), and no other files — there are no figures.

## Where every number comes from

| Paper | Source | Reproduce |
|-------|--------|-----------|
| Tables 2 and 4 (seed 7) | `benchmarks/REPORT.md` | `make bench` |
| Table 3 (50-seed sweep) | `benchmarks/seed_sweep.py` | `python benchmarks/seed_sweep.py --n 50` |
| 0.25 ms overhead | `scripts/bench_proxy.py` | `python scripts/bench_proxy.py` |
| 28/28 conformance | `spec/conformance/` | `python spec/conformance/run_conformance.py` |
| 305 tests | `tests/` | `python -m pytest` |

## References

All ten entries in `references.bib` were generated from the arXiv API record for
each ID, not typed by hand. `docs/blueprint.md` also mentions **LiSeCo** and
**RE-Control**; an arXiv search did not find them, so they are *not* cited.
Add them only after locating the actual papers.

## Before submitting

- [ ] Add a `LICENSE` file (pyproject declares Apache-2.0; none is in the repo) and
      then restore the license statement in Section 4.
- [ ] Confirm author name/affiliation/email and the arXiv category
      (suggest cs.AI primary, cs.SE or cs.CR secondary).
- [ ] Re-read the claims against `docs/blueprint.md` §0 "Claims to NEVER make".
- [ ] Decide whether to wait for real-model results (stronger) or submit as a
      methodology/systems preprint now (this draft).
- [ ] Publishing to arXiv is external and irreversible: human submits.
