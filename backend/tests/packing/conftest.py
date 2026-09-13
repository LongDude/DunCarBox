"""Small exact oracle independent of the production fractional-search loop."""

from itertools import product

import pytest
import z3

from app.packing.strategies import volume
from app.packing.z3_constraints import _build_model, compatible_box_types, objective
from app.packing.z3_model import _extract
from app.packing.z3_support import full_support


@pytest.fixture
def exact_optimum():
    def solve(request):
        types = compatible_box_types(request)
        model = _build_model(request, types, z3.Context(), symmetry=False)
        full_support(model)
        count = sum(p.quantity for p in request.products)
        # Enumerate denominators independently; at a fixed box volume, maximum
        # used volume is exactly maximum fill. No incumbent bounds are applied.
        denominators = {
            sum(n * volume(box) for n, box in zip(counts, types, strict=True))
            for counts in product(*(range(min(count, box.available_count) + 1) for box in types))
            if sum(counts) <= count
        }
        best = None
        for denominator in sorted(denominators):
            model.optimizer.push()
            model.optimizer.add(model.scores[2] == denominator)
            model.optimizer.set(timeout=10_000)
            status = model.optimizer.check()
            assert status in (z3.sat, z3.unsat)
            if status == z3.sat:
                assert all(h.lower().eq(h.upper()) for h in model.objectives)
                candidate = _extract(request, model, model.optimizer.model())
                if best is None or objective(candidate) < objective(best):
                    best = candidate
            model.optimizer.pop()
        assert best is not None
        return best

    return solve
