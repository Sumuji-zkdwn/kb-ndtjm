# Private WFS operator-loop reintegration

The portable shared controller in `loopcore/engine.py` is synchronized
from the companion `primitive-lean` reentry PR. The adapter imports the
original **private** `quantum/wfs_mobile_ci.py`; source and secrets
remain in this private repository.

Run locally:

```bash
python -m unittest discover -s tests -p test_loopcore.py -v
python -m loopcore run --domain wfs --root build/operator-loop-wfs
python -m loopcore audit --domain wfs --root build/operator-loop-wfs --recheck
```

The WFS finite candidate catalogue has exactly three entries
`google`, `public`, `scaled52`. One command invocation generates one
new model and validates the exact Boolean ANF phase, register restoration
and 120 deterministic samples. On success it appends a hash-linked
record, which excludes duplicates on the next invocation. Rechecking
that state is mandatory before continuing.

`loopcore/adapters/finite.py` is a portable copy of the public finite
adapter, not a substitute for actual Lean compilation. The existing
`wfs-local.yml` additionally tests the extracted loop, but Kickmix
parser and official DQI stages remain independent. The official Kaggle
submission is never invoked automatically.

The hash chain is an integrity warning, not an authenticity signature.
The independent local WFS validator cannot certify the full contest
solution. Do not infer general intelligence or new theorem discovery
from bounded enumerated operator growth.
