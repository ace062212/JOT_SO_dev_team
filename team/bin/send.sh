#!/usr/bin/env bash
# 팀원에게 메시지 보내기: send.sh <받는사람ID> "<메시지>"
exec python3 -I "$(dirname "$(readlink -f "$0")")/mail.py" send "$@"
