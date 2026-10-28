# Notebook sources

`notebooks/cpu-c8b.ipynb` is a copy of the existing Coverage c8b submission candidate.
It retains its existing official ARC Prize adapter and bundled policy. The official
framework is MIT licensed; its notice is in `licenses/ARC-Prize-MIT.txt`.

`notebooks/gpu-baseline.ipynb` preserves the code cells of Daniel Franzen's
[Milestone 2 solution, Kaggle version 3](https://www.kaggle.com/code/dfranzen/arc-agi-3-milestone-2-solution?scriptVersionId=354920985).
It derives from [da-fr/arc-agi-3-solution](https://github.com/da-fr/arc-agi-3-solution)
and Tufa Labs' Duck harness. The original Apache 2.0 license is included in
`licenses/Franzen-Apache-2.0.txt`.

`notebooks/gpu-memory.ipynb` preserves the existing local evidence-memory v1
extension of that baseline. These are alternative members of the same GPU line.

The GPU profiles now select the separate `*-connected.ipynb` derived copies.
Both isolate competition gateway discovery from local environment files and use
a short non-competition connection run; the original competition solver settings
remain in the rerun branch. The original files above are retained unchanged.
`notebooks/cpu-c8b-probe64.ipynb` derives one CPU policy parameter experiment.
`DERIVED_CANDIDATES.json` records all derived code hashes and changes.

Historical outputs and execution metadata are removed; all code cell sources are
preserved. `SOURCES.json` records original and imported hashes. Notebook identity
does not establish that models, inputs, dependencies or runtime were executed.
The notebook downloads/installs and input dependencies retain their own notices.
The Qwen models have their own community license and are not bundled here.
This package includes no model weights or downloaded ARC game source.
