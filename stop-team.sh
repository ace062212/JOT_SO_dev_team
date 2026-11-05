#!/usr/bin/env bash
# 팀 전원 퇴근 (tmux 세션 종료). 사무실 문서와 코드는 그대로 남는다.
SESSION="${SESSION:-aiteam}"
tmux kill-session -t "$SESSION" 2>/dev/null && echo "전원 퇴근 완료" || echo "출근한 팀이 없습니다"
