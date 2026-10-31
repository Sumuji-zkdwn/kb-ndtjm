from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np


@dataclass(frozen=True)
class Rule:
    """A pure grid transformation; None means the rule is inapplicable."""

    name: str
    fn: Callable[[np.ndarray], np.ndarray | None] = field(compare=False, repr=False)
    cost: float = 1.0
    family: str = "generic"

