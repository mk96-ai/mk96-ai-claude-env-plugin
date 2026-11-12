"""Entry point: python core/mk96env.py import|export|setup --clone PATH [--url URL]."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mk96env_core.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
