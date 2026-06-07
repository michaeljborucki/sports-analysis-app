"""Put the shared ``agents/`` directory on sys.path so ``import universal`` works
regardless of the directory pytest is invoked from."""
import os
import sys

_AGENTS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _AGENTS_ROOT not in sys.path:
    sys.path.insert(0, _AGENTS_ROOT)
