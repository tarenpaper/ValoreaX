"""Load the backend ML contract modules without importing the Flask app package.

`backend/app/__init__.py` pulls in Flask/SQLAlchemy, which this pipeline must
not depend on. `app/ml/data.py` itself is stdlib-only, so we load it by file
path. If the contract ever gains non-stdlib imports, surface that here loudly
instead of silently drifting.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent / "backend"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load contract module at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_contract():
    """Return the `app.ml.data` module from the backend tree."""
    data_py = _BACKEND / "app" / "ml" / "data.py"
    if not data_py.exists():
        raise FileNotFoundError(f"Backend contract not found at {data_py}")
    return _load("valoreax_ml_data_contract", data_py)
