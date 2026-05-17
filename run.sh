#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ ! -d venv ]; then
    python3 -m venv venv
    source venv/bin/activate
    pip install pyside6 opencv-python numpy
else
    source venv/bin/activate
fi

exec python3 main.py "$@"
