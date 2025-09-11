#!/bin/sh
# Ez a script biztosítja, hogy a környezeti változók (mint a $PORT)
# megfelelően be legyenek helyettesítve, mielőtt a szerver elindul.

set -e

# Indítjuk a Gunicorn szervert a behelyettesített PORT változóval
gunicorn --worker-tmp-dir /dev/shm --bind 0.0.0.0:${PORT} main:app
