"""Internal launch gate. Never executes a target without parent acknowledgement."""
import argparse
import ctypes
import os
import runpy
import signal
import sys


def main():
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--module")
    target.add_argument("--path")
    parser.add_argument("--parent-pid", required=True, type=int)
    args = parser.parse_args()
    if sys.platform == "linux":
        # Preserve parent-death cleanup when children have their own process group.
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Cannot set parent-death signal")
        if os.getppid() != args.parent_pid:
            return
    if sys.stdin.readline().strip() != "go":
        return
    if args.module:
        sys.argv = [args.module]
        runpy.run_module(args.module, run_name="__main__")
    else:
        sys.argv = [args.path]
        runpy.run_path(args.path, run_name="__main__")


if __name__ == "__main__":
    main()
