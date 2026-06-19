#!/usr/bin/env bash
set +e

python -m pip install --quiet pytest==8.4.1
python -m pytest -q /tests/test_romans.py
status=$?

if [ "$status" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi

exit "$status"
