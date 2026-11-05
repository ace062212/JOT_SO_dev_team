#!/usr/bin/env bash
# 직원 한 명을 출근시킨다: 역할 프롬프트 + 모델 + 권한을 붙여서 claude 실행
# 사용법: team/bin/hire.sh <bujang|chajang|gwajang|daeri-a|daeri-b|sawon>
#   기본: 지난번 대화가 있으면 이어서 재출근 (FRESH=1 이면 새 대화로 시작)
set -euo pipefail

ROLE="${1:?역할 ID를 지정하세요}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TEAM="$ROOT/team"

# 직급별 모델 (환경변수로 덮어쓰기 가능: MODEL_SAWON=sonnet ./start-team.sh)
case "$ROLE" in
  bujang)  MODEL="${MODEL_BUJANG:-opus}";    PROMPT=bujang;  DIR="$ROOT" ;;
  chajang) MODEL="${MODEL_CHAJANG:-opus}";   PROMPT=chajang; DIR="$ROOT" ;;
  gwajang) MODEL="${MODEL_GWAJANG:-opus}";   PROMPT=gwajang; DIR="$ROOT/project" ;;
  daeri-a) MODEL="${MODEL_DAERI:-sonnet}";   PROMPT=daeri;   DIR="$ROOT/wt/daeri-a" ;;
  daeri-b) MODEL="${MODEL_DAERI:-sonnet}";   PROMPT=daeri;   DIR="$ROOT/wt/daeri-b" ;;
  sawon)   MODEL="${MODEL_SAWON:-haiku}";    PROMPT=sawon;   DIR="$ROOT" ;;
  *) echo "알 수 없는 역할: $ROLE" >&2; exit 1 ;;
esac

SYS="$( { cat "$TEAM/README.md"; echo; cat "$TEAM/roles/$PROMPT.md"; } \
        | sed -e "s#{{ME}}#$ROLE#g" -e "s#{{ROOT}}#$ROOT#g" )"

# 상태 훅·메시지 시스템이 누구인지 알 수 있게
export TEAM_DIR="$TEAM" TEAM_ROLE="$ROLE"
export PATH="$TEAM/bin:$PATH"
mkdir -p "$TEAM/status" "$TEAM/inbox"
# 우체부가 이 직원의 tmux 칸을 찾을 수 있게
[ -n "${TMUX_PANE:-}" ] && echo "$TMUX_PANE" > "$TEAM/status/$ROLE.pane"

# 지난 대화 이어받기
RESUME_ARGS=()
if [ -z "${FRESH:-}" ] && [ -f "$TEAM/status/$ROLE.json" ]; then
  SID="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("session_id",""))' "$TEAM/status/$ROLE.json" 2>/dev/null || true)"
  if [ -n "$SID" ] && compgen -G "$HOME/.claude/projects/*/$SID.jsonl" >/dev/null; then
    RESUME_ARGS=(--resume "$SID")
  fi
fi

if [ ${#RESUME_ARGS[@]} -gt 0 ]; then
  # 이어받은 대화에는 예전 시스템 프롬프트가 남아 있으므로, 최신 규칙 파일을 직접 다시 읽게 한다
  KICKOFF="재출근했습니다. 팀 규칙이 갱신됐을 수 있습니다. 시스템 프롬프트보다 파일이 최신이니 $TEAM/README.md 와 $TEAM/roles/$PROMPT.md 를 다시 읽고, 둘이 다르면 파일을 따르세요. (업무 전달은 send.sh로 직접 합니다.) 다 읽었으면 '[$ROLE] 재출근 완료' 한 줄로만 답하세요."
else
  KICKOFF="출근했습니다. 팀 규칙과 당신의 역할을 숙지했다면 '[$ROLE] 출근 완료' 한 줄로만 답하고 지시를 기다리세요."
fi

cd "$DIR"
# --add-dir 은 가변 인자라서 다른 옵션 앞에 둔다
exec claude \
  --add-dir "$TEAM" "$ROOT" \
  "${RESUME_ARGS[@]}" \
  --model "$MODEL" \
  --settings "$TEAM/settings/$PROMPT.json" \
  --append-system-prompt "$SYS" \
  "$KICKOFF"
