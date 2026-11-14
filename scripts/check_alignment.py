"""Backward-compatible wrapper for alignment checking & plotting (delegates to phrase_timing.py --plot)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phrase_timing

if __name__ == '__main__':
    phrase_timing.main(['--plot', *sys.argv[1:]])
