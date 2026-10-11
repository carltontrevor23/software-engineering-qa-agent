import sys
from pathlib import Path

# Make `subscription_service` importable, the same way the sandbox does via PYTHONPATH.
SUT_DIR = Path(__file__).resolve().parent.parent
if str(SUT_DIR) not in sys.path:
    sys.path.insert(0, str(SUT_DIR))
