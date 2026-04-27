"""Entry point for ``python -m gpa``.

Dispatches to the user-facing CLI (``gpa.cli.main``).  The engine launcher
remains accessible explicitly via ``python -m gpa.launcher``.
"""

import sys

from gpa.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
