import sys
import os
import logging
import warnings
from pathlib import Path

# Ensure repository root is on sys.path so local modules import cleanly
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep test output minimal (logs suppressed); warnings handled via pytest config
logging.disable(logging.CRITICAL)
warnings.filterwarnings("default")
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
