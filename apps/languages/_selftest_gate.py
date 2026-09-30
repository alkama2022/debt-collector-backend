"""
Runs the Django-free subset of apps/languages/tests.py without Django.

Django is not installed in this checkout's venv, so `manage.py test` cannot
run. This harness stubs the small number of Django imports the content tests
need and executes them, so the quality gate is still verified rather than
merely written.

    .venv/Scripts/python.exe backend/apps/languages/_selftest_gate.py
"""
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, BACKEND)

# apps.languages.tests imports django.test.TestCase at module scope for the
# registry gate. Provide a placeholder so the content tests can be collected;
# the registry gate is skipped because it genuinely needs a database.
if "django" not in sys.modules:
    django_mod = types.ModuleType("django")
    conf_mod = types.ModuleType("django.conf")
    conf_mod.settings = types.SimpleNamespace(FRONTEND_URL="https://collectnaija.test")
    django_mod.conf = conf_mod
    test_mod = types.ModuleType("django.test")

    class _StubTestCase(unittest.TestCase):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)

    test_mod.TestCase = _StubTestCase
    django_mod.test = test_mod
    sys.modules["django"] = django_mod
    sys.modules["django.conf"] = conf_mod
    sys.modules["django.test"] = test_mod

import apps.languages.tests as t  # noqa: E402
import apps.languages.tests_voice as tv  # noqa: E402
import apps.comms.tests_language as tc  # noqa: E402
import apps.audit.tests_audit as ta  # noqa: E402

loader = unittest.TestLoader()
suite = unittest.TestSuite()
for mod in (t, tv, tc, ta):
    suite.addTests(loader.loadTestsFromModule(mod))

# Drop the DB-backed registry gate (it needs a real Django/DB stack).
filtered = unittest.TestSuite()


def _keep(test):
    return "LanguageRegistryGateTests" not in type(test).__name__


def _flatten(s):
    for x in s:
        if isinstance(x, unittest.TestSuite):
            for y in _flatten(x):
                yield y
        else:
            yield x


skipped = 0
for test in _flatten(suite):
    if _keep(test):
        filtered.addTest(test)
    else:
        skipped += 1

print("Running %d quality-gate tests (skipped %d DB-backed registry tests)\n"
      % (filtered.countTestCases(), skipped))
result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(filtered)
print("")
if skipped:
    print("NOTE: %d LanguageRegistryGateTests require Django + a database." % skipped)
sys.exit(0 if result.wasSuccessful() else 1)
