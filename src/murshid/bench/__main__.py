"""Entry point for `python -m murshid.bench`."""

from murshid.bench.runner import main

if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
