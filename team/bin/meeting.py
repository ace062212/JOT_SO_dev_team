#!/usr/bin/env python3
"""회의실: 각 직원의 '회의 분신'(역할 프롬프트를 가진 일회성 claude -p)을 불러 라운드제로 회의한다.

  meeting.sh "<주제와 맥락>" [참석자 csv | all]     → 백그라운드로 회의 시작, 즉시 반환

- 라운드마다 참석자 전원이 동시에 발언하거나 PASS 한다.
- 2라운드부터는 앞 라운드까지의 발언 전체를 보고 반응한다.
- 한 라운드에 전원이 PASS 하거나 최대 라운드(MEETING_ROUNDS, 기본 3)에 도달하면 종료.
- 회의록: team/meetings/M-XXX.md  / 진행 상황은 events.jsonl 에 기록되어 채팅창에 실시간 표시
- 종료 후 소집자(부장)에게 메시지로 회의록 경로를 보낸다.
- 분신은 읽기 도구(Read/Glob/Grep)만 쓸 수 있고, 실제 직원 세션에는 영향을 주지 않는다.
"""
import json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

BIN = os.path.dirname(os.path.abspath(__file__))
TEAM = os.path.dirname(BIN)
ROOT = os.path.dirname(TEAM)
MEET = os.path.join(TEAM, "meetings")
RUNNING = os.path.join(MEET, ".running")
MEMBERS = {"bujang": "부장", "chajang": "차장", "gwajang": "과장",
           "daeri-a": "대리A", "daeri-b": "대리B", "sawon": "사원"}
ROLE_FILE = {"bujang": "bujang", "chajang": "chajang", "gwajang": "gwajang",
             "daeri-a": "daeri", "daeri-b": "daeri", "sawon": "sawon"}
DEFAULT_ATTENDEES = ["chajang", "gwajang", "daeri-a", "daeri-b", "sawon"]

MEETING_RULES = """
# 지금 상황: 회의 참석
너는 지금 회의에 참석한 **{name}({me})의 분신**이다. 위의 역할과 "회의에서의 관점"을 그대로 가진다.
- 회의 중에는 파일 수정, 명령 실행, 메시지 전송을 할 수 없다. **발언만** 한다.
- 판단에 필요하면 Read/Glob/Grep으로 참고 파일을 볼 수 있다. 꼭 필요한 것만 짧게 본다.
- 출력은 오직 발언 내용만 쓴다. 머리말, 이름표, 따옴표, 마크다운 제목은 쓰지 않는다.
- 할 말이 없으면 정확히 `PASS` 한 단어만 출력한다.
- 발언하면 **3문장 이내**, 존댓말, 실제 회의처럼 구어체로 말한다.
- 앞사람이 한 말을 되풀이하거나 단순히 동의하지 않는다. 새로운 관점, 반대, 질문, 구체적인 아이디어만 말한다.
- 특정 참석자에게 직접 묻거나 반박해도 된다. (예: "과장님 말씀과 달리...")
"""


def now():
    return datetime.now().isoformat(timespec="seconds")


def log_event(rec):
    os.makedirs(os.path.join(TEAM, "status"), exist_ok=True)
    with open(os.path.join(TEAM, "status", "events.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def system_prompt(me):
    s = open(os.path.join(TEAM, "README.md"), encoding="utf-8").read() + "\n\n" + \
        open(os.path.join(TEAM, "roles", ROLE_FILE[me] + ".md"), encoding="utf-8").read()
    s = s.replace("{{ME}}", me).replace("{{ROOT}}", ROOT)
    return s + "\n" + MEETING_RULES.format(name=MEMBERS[me], me=me)


def model_for(me):
    key = "MEETING_MODEL_" + me.upper().replace("-", "_")
    return os.environ.get(key) or os.environ.get("MEETING_MODEL") or "sonnet"


def speak(me, topic, transcript, rnd, rounds):
    prompt = (f"회의 주제:\n{topic}\n\n"
              f"지금까지의 회의 내용:\n{transcript or '(아직 발언 없음. 첫 라운드입니다.)'}\n\n"
              f"라운드 {rnd}/{rounds}. {MEMBERS[me]}({me})로서 발언하세요. 할 말이 없으면 PASS.")
    env = {k: v for k, v in os.environ.items() if k not in ("TEAM_ROLE",)}
    cmd = ["claude", "-p", "--tools", "Read", "Glob", "Grep",
           "--model", model_for(me),
           "--settings", os.path.join(TEAM, "settings", "meeting.json"),
           "--strict-mcp-config", "--no-session-persistence",
           "--append-system-prompt", system_prompt(me),
           prompt]
    try:
        r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True,
                           timeout=int(os.environ.get("MEETING_TIMEOUT", "240")), stdin=subprocess.DEVNULL)
        out = (r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        out = "PASS"
    if not out or re.fullmatch(r"\W*PASS\W*", out, re.I):
        return None
    out = re.sub(r"^\s*\**\s*(" + re.escape(MEMBERS[me]) + r"|" + re.escape(me) + r")[^:：]{0,12}[:：]\s*", "", out)
    out = " ".join(out.split())
    return out[:700]


def next_id():
    os.makedirs(MEET, exist_ok=True)
    nums = [int(m.group(1)) for n in os.listdir(MEET) if (m := re.match(r"M-(\d+)\.md$", n))]
    return f"M-{(max(nums) + 1) if nums else 1:03d}"


def run(mid, organizer, attendees, topic):
    rounds = int(os.environ.get("MEETING_ROUNDS", "3"))
    path = os.path.join(MEET, f"{mid}.md")
    names = ", ".join(f"{MEMBERS[a]}({a})" for a in attendees)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 회의록 {mid}\n\n- 일시: {now()}\n- 소집: {MEMBERS.get(organizer, '사장님')}\n"
                f"- 참석: {names}\n\n## 주제\n{topic}\n\n## 발언\n")
    log_event({"id": organizer, "event": "MeetingStart", "meeting": mid, "attendees": attendees,
               "topic": topic[:200], "at": now()})
    transcript = ""
    spoke_total = 0
    for rnd in range(1, rounds + 1):
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n### 라운드 {rnd}\n")
        spoke = 0
        with ThreadPoolExecutor(max_workers=len(attendees)) as ex:
            futs = {ex.submit(speak, a, topic, transcript, rnd, rounds): a for a in attendees}
            lines = []
            for fu in as_completed(futs):
                a = futs[fu]
                try:
                    said = fu.result()
                except Exception as e:
                    said = None
                if said:
                    spoke += 1
                    line = f"- **{MEMBERS[a]}**: {said}"
                    lines.append(f"[R{rnd}] {MEMBERS[a]}: {said}")
                    log_event({"id": a, "event": "MeetingSay", "meeting": mid, "round": rnd, "text": said, "at": now()})
                else:
                    line = f"- {MEMBERS[a]}: (패스)"
                    log_event({"id": a, "event": "MeetingPass", "meeting": mid, "round": rnd, "at": now()})
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        transcript += ("\n" if transcript else "") + "\n".join(lines)
        spoke_total += spoke
        if spoke == 0:
            break
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n## 결정 / 액션 아이템\n<!-- 소집자(부장)가 작성: 결정 사항, 액션 아이템(담당자·티켓), 보류한 의견 -->\n")
    log_event({"id": organizer, "event": "MeetingEnd", "meeting": mid, "rounds": rnd, "statements": spoke_total,
               "file": f"team/meetings/{mid}.md", "at": now()})
    if organizer in MEMBERS:
        env = dict(os.environ, TEAM_DIR=TEAM, TEAM_ROLE="meeting")
        subprocess.run(["python3", "-I", os.path.join(BIN, "mail.py"), "send", organizer,
                        f"[{mid}] 회의 종료 ({rnd}라운드, 발언 {spoke_total}회). 회의록: team/meetings/{mid}.md "
                        f"— 읽고 '결정 / 액션 아이템'을 작성한 뒤 담당자에게 전달하세요."],
                       env=env, capture_output=True)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "_run":
        _, _, mid, organizer, attendees, topic = sys.argv
        try:
            run(mid, organizer, attendees.split(","), topic)
        finally:
            try:
                os.remove(RUNNING)
            except FileNotFoundError:
                pass
        return
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        sys.exit('사용법: meeting.sh "<주제와 맥락, 참고 파일 경로>" [참석자 csv | all]')
    topic = sys.argv[1].strip()
    who = sys.argv[2] if len(sys.argv) >= 3 else "all"
    organizer = os.environ.get("TEAM_ROLE") or "boss"
    attendees = DEFAULT_ATTENDEES if who == "all" else [w.strip() for w in who.split(",") if w.strip()]
    bad = [a for a in attendees if a not in MEMBERS]
    if bad:
        sys.exit(f"알 수 없는 참석자: {bad}  (가능: {', '.join(MEMBERS)})")
    attendees = [a for a in attendees if a != organizer] or DEFAULT_ATTENDEES
    os.makedirs(MEET, exist_ok=True)
    if os.path.exists(RUNNING):
        sys.exit(f"이미 진행 중인 회의가 있습니다: {open(RUNNING).read().strip()}. 끝난 뒤 소집하세요.")
    mid = next_id()
    open(RUNNING, "w").write(mid)
    log = open(os.path.join(MEET, f".{mid}.log"), "w")
    subprocess.Popen(["python3", "-I", "-u", os.path.abspath(__file__), "_run", mid, organizer, ",".join(attendees), topic],
                     stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    print(f"회의 {mid} 소집됨 · 참석: {', '.join(MEMBERS[a] for a in attendees)} · 최대 {os.environ.get('MEETING_ROUNDS', '3')}라운드.\n"
          f"백그라운드로 진행되며 끝나면 회의록 경로가 메시지로 옵니다. 지금은 응답을 마치세요.")


if __name__ == "__main__":
    main()
