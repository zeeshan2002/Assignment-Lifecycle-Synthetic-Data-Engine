"""
Deterministic PRNG with independent, key-derived sub-streams.

`spawn(*key)` derives a child generator from (seed, key) via SHA-256, so the stream used for, say,
one learner/assignment bundle does not depend on how many random numbers other bundles consumed.
That makes anomaly injection and truncation non-disruptive to unrelated rows.
"""

import hashlib
import random
from typing import List, Sequence, Any


class SeededRNG:
    def __init__(self, seed: int):
        self.seed = seed
        self._r = random.Random(seed)

    def spawn(self, *key) -> "SeededRNG":
        digest = hashlib.sha256("|".join(str(p) for p in (self.seed,) + key).encode()).digest()
        return SeededRNG(int.from_bytes(digest[:8], "big"))

    def random(self) -> float:
        return self._r.random()

    def uniform(self, a: float, b: float) -> float:
        return self._r.uniform(a, b)

    def randint(self, a: int, b: int) -> int:
        return self._r.randint(a, b)

    def choice(self, seq: Sequence[Any]) -> Any:
        return self._r.choice(seq)

    def choices(self, seq: Sequence[Any], weights: Sequence[float] = None, k: int = 1) -> List[Any]:
        return self._r.choices(seq, weights=weights, k=k)

    def sample(self, population: Sequence[Any], k: int) -> List[Any]:
        return self._r.sample(population, k)

    def shuffle(self, seq: list) -> None:
        self._r.shuffle(seq)

    def gauss(self, mu: float, sigma: float) -> float:
        return self._r.gauss(mu, sigma)

    def betavariate(self, a: float, b: float) -> float:
        return self._r.betavariate(a, b)

    def expovariate(self, lambd: float) -> float:
        return self._r.expovariate(lambd)

    def lognormvariate(self, mu: float, sigma: float) -> float:
        return self._r.lognormvariate(mu, sigma)


def clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x
