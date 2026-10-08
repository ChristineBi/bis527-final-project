"""Build the project database from scratch.

    python run_pipeline.py              # every step
    python run_pipeline.py tabnet       # just one step

Steps, in order: tabnet, boundaries, build, check.

Optional steps, not run by default: download and convert fetch the raw
SINAN/SINASC microdata files from the DATASUS FTP server. That server does
not accept connections from outside Brazil, so we use TabNet instead.
"""
import sys
import time
from datetime import datetime
from pathlib import Path

STEPS = ["tabnet", "boundaries", "build", "check"]
OPTIONAL_STEPS = ["download", "convert"]
LOG_DIR = Path(__file__).resolve().parent / "logs"


class Tee:
    """Print to the screen and to a log file at the same time."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for s in self.streams:
            s.write(text)
            s.flush()

    def flush(self):
        for s in self.streams:
            s.flush()


def main(args):
    steps = args or STEPS
    unknown = [s for s in steps if s not in STEPS + OPTIONAL_STEPS]
    if unknown:
        sys.exit(f"unknown step(s) {unknown}; "
                 f"choose from {STEPS + OPTIONAL_STEPS}")
    problems = []
    for step in steps:
        start = time.time()
        print(f"\n=== {step} ===")
        if step == "tabnet":
            from pipeline import tabnet
            tabnet.run()
        elif step == "download":
            from pipeline import download
            found = download.run()
            problems += found
            if any(p.startswith("Could not connect") for p in found):
                print("Stopping: the later steps need the downloaded files.")
                break
        elif step == "convert":
            from pipeline import convert
            convert.run()
        elif step == "boundaries":
            from pipeline import boundaries
            boundaries.run()
        elif step == "build":
            from pipeline import build_db
            build_db.run()
        elif step == "check":
            from pipeline import check
            check.run()
        print(f"({step} took {time.time() - start:.0f}s)")
    if problems:
        print("\nProblems to look at:")
        for p in problems:
            print("  " + p)


if __name__ == "__main__":
    LOG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    with open(LOG_DIR / f"run-{stamp}.log", "w", encoding="utf-8") as log:
        sys.stdout = Tee(sys.__stdout__, log)
        sys.stderr = Tee(sys.__stderr__, log)
        try:
            main(sys.argv[1:])
        except BaseException:
            import traceback
            traceback.print_exc()
            raise
        finally:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
