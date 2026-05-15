"""
Root-level conftest.py — pytest path bootstrap.

Ensures /Users/shantanu/Mini_Anvil is on sys.path so that all test files
can do `from engine.xxx import ...` without a package install.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
