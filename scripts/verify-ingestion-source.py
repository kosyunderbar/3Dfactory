"""Compatibility entry point: S05 now delivers accepted TCP events automatically.
Use the current fresh-run verification and clean only the successful probe's own records in both DBs.
Historical S03 PENDING/cursor=1 assertions no longer describe the running system.
"""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("verify-delivery.py")), run_name="__main__")
