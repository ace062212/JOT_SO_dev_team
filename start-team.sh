#!/usr/bin/env bash
# AI 개발팀 6명을 tmux 세션 하나에 출근시킨다.
# 사용법:
#   ./start-team.sh               (기본) 사무실 레이아웃
#                                   0 부장실 : 왼쪽 부장(사장님 입력) | 오른쪽 팀 채팅 + 상태줄
#                                   1 작업실 : 나머지 5명 화면 (Ctrl+b z 로 한 칸 확대 토글)
#                                   2 우체부 : 메시지 전달 로그
#   LAYOUT=grid ./start-team.sh   한 화면 6칸 분할
#   LAYOUT=windows ./start-team.sh  한 명당 창 하나
#   SESSION=foo NO_ATTACH=1 ...   세션 이름 변경 / 접속하지 않고 백그라운드로만 띄우기
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SESSION="${SESSION:-aiteam}"
LAYOUT="${LAYOUT:-office}"
HIRE="${HIRE:-$ROOT/team/bin/hire.sh}"
CHAT="TEAM_DIR='$ROOT/team' python3 -I -u '$ROOT/team/bin/chat.py'; exec bash"
MAILMAN="TEAM_DIR='$ROOT/team' python3 -I -u '$ROOT/team/bin/mail.py' mailman; exec bash"

# 1) 대리 worktree 준비 (없을 때만)
for d in daeri-a daeri-b; do
  if [ ! -d "$ROOT/wt/$d" ]; then
    git -C "$ROOT/project" worktree add "$ROOT/wt/$d" -b "desk/$d" main
  fi
done

# 표시 이름 : 역할 ID
MEMBERS=("부장:bujang" "차장:chajang" "과장:gwajang" "대리A:daeri-a" "대리B:daeri-b" "사원:sawon")
cmd_for() { echo "$HIRE $1; echo; echo '[$1] 퇴근함. 다시 출근: $HIRE $1'; exec bash"; }

# 여러 칸을 한 창에 타일로 배치: tile <창 대상> <멤버...>
tile() {
  local target="$1"; shift
  for m in "$@"; do
    local name="${m%%:*}" role="${m##*:}"
    local pane
    pane=$(tmux split-window -P -F '#{pane_id}' -t "$target" -c "$ROOT" "$(cmd_for "$role")")
    tmux set-option -p -t "$pane" @member "$name"
    tmux select-layout -t "$target" tiled >/dev/null
  done
}

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "이미 출근한 팀이 있습니다 → 접속합니다. (레이아웃을 바꾸려면 ./stop-team.sh 후 다시 실행)"
else
  case "$LAYOUT" in
    office)
      # 0 부장실: 부장 | 채팅
      p=$(tmux new-session -d -P -F '#{pane_id}' -s "$SESSION" -n "부장실" -x 240 -y 60 -c "$ROOT" "$(cmd_for bujang)")
      tmux set-option -p -t "$p" @member "부장  ← 사장님은 여기서만 입력"
      c=$(tmux split-window -h -d -P -F '#{pane_id}' -l 40% -t "$p" -c "$ROOT" "$CHAT")
      tmux set-option -p -t "$c" @member "💬 팀 채팅"
      # 1 작업실: 나머지 5명
      first=$(tmux new-window -d -P -F '#{pane_id}' -t "$SESSION:1" -n "작업실" -c "$ROOT" "$(cmd_for chajang)")
      tmux set-option -p -t "$first" @member "차장"
      tile "$SESSION:작업실" "과장:gwajang" "대리A:daeri-a" "대리B:daeri-b" "사원:sawon"
      ;;
    grid)
      p=$(tmux new-session -d -P -F '#{pane_id}' -s "$SESSION" -n "팀전체" -x 240 -y 60 -c "$ROOT" "$(cmd_for bujang)")
      tmux set-option -p -t "$p" @member "부장"
      tile "$SESSION:0" "${MEMBERS[@]:1}"
      ;;
    *)
      tmux new-session -d -s "$SESSION" -n "부장" -c "$ROOT" "$(cmd_for bujang)"
      for m in "${MEMBERS[@]:1}"; do
        tmux new-window -d -t "$SESSION" -n "${m%%:*}" -c "$ROOT" "$(cmd_for "${m##*:}")"
      done
      ;;
  esac
  tmux set-option -t "$SESSION" pane-border-status top
  tmux set-option -t "$SESSION" pane-border-format " #{?pane_active,#[reverse],}#{@member}#[default] #{?window_zoomed_flag,(확대중 · Ctrl+b z 로 복귀),} "
  tmux set-option -t "$SESSION" status-left "#[bold] AI팀 "
  tmux select-window -t "$SESSION:0"
  tmux select-pane -t "$SESSION:0.0"
fi

# 우체부: 직원 간 메시지를 자동 전달 (별도 창)
if ! tmux list-windows -t "$SESSION" -F '#{window_name}' | grep -qx '우체부'; then
  tmux new-window -d -t "$SESSION" -n "우체부" -c "$ROOT" "$MAILMAN"
fi

[ -n "${NO_ATTACH:-}" ] && { echo "백그라운드 출근 완료: tmux attach -t $SESSION"; exit 0; }
if [ -n "${TMUX:-}" ]; then
  tmux switch-client -t "$SESSION"
else
  tmux attach -t "$SESSION"
fi
