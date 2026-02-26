"""Fix namespace collision between tests/benchmarks/ and project-root benchmarks/.

pytest registers tests/benchmarks/ as the ``benchmarks`` package.  We cannot
replace that entry (pytest needs it to locate test modules), but we *can*
inject the real ``benchmarks.longmemeval`` sub-package into sys.modules so
that ``from benchmarks.longmemeval import ...`` resolves to the project-root
benchmarks/longmemeval/ directory.
"""

import importlib
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Temporarily remove tests/benchmarks from sys.modules so we can import the
# real benchmarks package, then restore it.
_test_benchmarks = sys.modules.pop("benchmarks", None)

# Also remove any stale benchmarks.* entries from tests/
_stale = {k: sys.modules.pop(k) for k in list(sys.modules) if k.startswith("benchmarks.")}

# Import the real benchmarks.longmemeval package chain.
import benchmarks as _real_benchmarks  # noqa: E402
import benchmarks.longmemeval  # noqa: E402
import benchmarks.longmemeval.indexer  # noqa: E402
import benchmarks.longmemeval.models  # noqa: E402
import benchmarks.longmemeval.retriever  # noqa: E402

# Save the real sub-package references.
_real_lme = sys.modules["benchmarks.longmemeval"]
_real_indexer = sys.modules["benchmarks.longmemeval.indexer"]
_real_models = sys.modules["benchmarks.longmemeval.models"]
_real_retriever = sys.modules["benchmarks.longmemeval.retriever"]

# Restore tests/benchmarks as the top-level ``benchmarks`` package.
if _test_benchmarks is not None:
    sys.modules["benchmarks"] = _test_benchmarks

# Restore any stale entries that are not overridden by the real package.
for key, mod in _stale.items():
    if key not in sys.modules:
        sys.modules[key] = mod

# Inject the real sub-package entries so imports work from test modules.
sys.modules["benchmarks.longmemeval"] = _real_lme
sys.modules["benchmarks.longmemeval.indexer"] = _real_indexer
sys.modules["benchmarks.longmemeval.models"] = _real_models
sys.modules["benchmarks.longmemeval.retriever"] = _real_retriever

# Also make the sub-package accessible as an attribute of tests/benchmarks.
if _test_benchmarks is not None:
    _test_benchmarks.longmemeval = _real_lme  # type: ignore[attr-defined]
