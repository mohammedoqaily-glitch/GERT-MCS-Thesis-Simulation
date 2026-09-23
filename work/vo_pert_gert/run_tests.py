import pathlib
import sys
import unittest

root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(root))
suite = unittest.defaultTestLoader.discover(str(root / "tests"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
print(f"PASSED={result.testsRun - len(result.failures) - len(result.errors)}")
print(f"FAILED={len(result.failures) + len(result.errors)}")
raise SystemExit(0 if result.wasSuccessful() else 1)

