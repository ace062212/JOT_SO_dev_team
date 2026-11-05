#!/usr/bin/env python3
"""Claude Code 훅 → 직원 실시간 상태 기록.

각 직원 세션의 훅 이벤트를 받아서
  team/status/<ID>.json      : 현재 상태 (덮어쓰기)
  team/status/events.jsonl   : 이벤트 누적 로그 (타임라인용)
에 기록한다. 환경변수 TEAM_DIR, TEAM_ROLE 은 hire.sh 가 설정한다.
어떤 경우에도 세션을 방해하지 않도록 항상 exit 0.
"""
import json, os, sys, tempfile
from datetime import datetime

def target_of(tool, inp):
    if not isinstance(inp, dict):
        return ""
    for key in ("file_path", "notebook_path", "path", "command", "pattern", "url", "query", "description", "prompt"):
        v = inp.get(key)
        if v:
            v = str(v).replace("\n", " ")
            return v[:120]
    return ""

def main():
    team = os.environ.get("TEAM_DIR")
    role = os.environ.get("TEAM_ROLE")
    if not team or not role:
        return
    try:
        ev = json.load(sys.stdin)
    except Exception:
        ev = {}
    name = ev.get("hook_event_name", "")
    now = datetime.now().isoformat(timespec="seconds")

    rec = {"id": role, "event": name, "at": now, "session_id": ev.get("session_id", "")}
    if name == "SessionStart":
        rec.update(state="idle", activity="출근")
    elif name == "UserPromptSubmit":
        rec.update(state="working", activity="지시 받음", detail=str(ev.get("prompt", ""))[:120].replace("\n", " "))
    elif name == "PreToolUse":
        tool = ev.get("tool_name", "")
        rec.update(state="working", activity="도구 사용", tool=tool, target=target_of(tool, ev.get("tool_input")))
    elif name == "Notification":
        msg = str(ev.get("message", ""))
        if ev.get("notification_type") == "idle_prompt" or "waiting for your input" in msg:
            rec.update(state="idle", activity="응답 완료, 대기")   # 그냥 입력을 기다리는 중
        else:
            rec.update(state="waiting", activity="사장님 확인 대기", detail=msg[:120])  # 권한 승인 등
    elif name == "Stop":
        rec.update(state="idle", activity="응답 완료, 대기")
    elif name == "SessionEnd":
        rec.update(state="offline", activity="퇴근")
    else:
        return

    d = os.path.join(team, "status")
    os.makedirs(d, exist_ok=True)
    # 현재 상태: 원자적 덮어쓰기
    fd, tmp = tempfile.mkstemp(dir=d, prefix=f".{role}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(d, f"{role}.json"))
    # 누적 로그
    with open(os.path.join(d, "events.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
