"""Entry point: `python -m superplanner.worker [--concurrency N] [--kinds ...] [--id NAME] [--once] [--metrics-port P]`."""

import sys

from superplanner.jobs.worker import main

if __name__ == "__main__":
    sys.exit(main())
