#!/usr/bin/env bash
# 회의 소집: meeting.sh "<주제와 맥락>" [참석자 csv | all]
exec python3 -I "$(dirname "$(readlink -f "$0")")/meeting.py" "$@"
