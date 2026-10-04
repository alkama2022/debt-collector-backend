#!/usr/bin/env bash

set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --noinput

python manage.py migrate --noinput

# NOTE: Do NOT run `createsuperuser` here. It is not idempotent and fails with
# "That email is already taken" on every deploy after the first. The admin user
# is created/updated idempotently by `python manage.py ensure_admin` in the
# render.yaml startCommand. Do NOT start gunicorn here either — this is the
# build command; gunicorn is launched by the startCommand.
