"""
Production readiness test runner.
Sets up a safe test environment and runs the full Django test suite.
"""
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ["DEBUG"] = "True"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["DATABASE_URL"] = ""
os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
os.environ["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/1"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "True"
os.environ["WHATSAPP_PROVIDER"] = "mock"
os.environ["VOICE_PROVIDER"] = "mock"
os.environ["EMAIL_PROVIDER"] = "mock"

import django
django.setup()

from django.core.management import call_command

print("=" * 60)
print("DJANGO SYSTEM CHECK (--deploy)")
print("=" * 60)
try:
    call_command("check", "--deploy", verbosity=2)
    print("\n[PASSED] Django deploy check passed")
except Exception as e:
    print(f"\n[FAILED] Django deploy check failed: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("FULL TEST SUITE")
print("=" * 60)
try:
    call_command("test", "--verbosity=2", interactive=False)
    print("\n[PASSED] All tests passed")
except Exception as e:
    print(f"\n[FAILED] Tests failed: {e}")
    sys.exit(1)
