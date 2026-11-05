#!/usr/bin/env python3
"""팀 메시지 시스템.

  mail.py send <받는사람ID> "<메시지>"   우편함에 넣기 (보내는 사람 = $TEAM_ROLE, 없으면 boss=사장님)
  mail.py mailman                        우체부: 받는 사람이 idle일 때 그 tmux 칸에 자동 입력

안전장치
  - 받는 사람 상태가 idle일 때만 전달 (권한 승인 창에 Enter가 들어가는 사고 방지)
  - team/inbox/PAUSE 파일이 있으면 전달 중지 (메시지는 보관)
  - 핑퐁 감지: 같은 두 사람이 MAIL_LOOP_WINDOW초(기본 600) 안에 MAIL_LOOP_MAX회(기본 12) 이상 주고받는데
    그동안 진전(티켓 상태 변경 또는 git 커밋)이 없으면 → 그 두 사람 사이 전달만 보류 (나머지 팀은 계속 일함)
    보류 해제: rm team/inbox/HOLD_<a>+<b>
  - 최후 안전망: 시간당 전체 전달 MAIL_MAX_PER_HOUR(기본 600) 초과 시 전체 PAUSE
"""
import fcntl, json, os, subprocess, sys, time
from collections import deque
from datetime import datetime

MEMBERS = {"bujang": "부장", "chajang": "차장", "gwajang": "과장",
           "daeri-a": "대리A", "daeri-b": "대리B", "sawon": "사원"}
NAMES = dict(MEMBERS, boss="사장님", meeting="회의실")
TEAM = os.environ.get("TEAM_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(TEAM, "inbox")
STATUS = os.path.join(TEAM, "status")
PAUSE = os.path.join(INBOX, "PAUSE")
LOCK = os.path.join(INBOX, ".lock")


def now():
    return datetime.now().isoformat(timespec="seconds")


class Lock:
    def __enter__(self):
        os.makedirs(INBOX, exist_ok=True)
        self.f = open(LOCK, "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def log_event(rec):
    os.makedirs(STATUS, exist_ok=True)
    with open(os.path.join(STATUS, "events.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def send(to, text):
    frm = os.environ.get("TEAM_ROLE") or "boss"
    if to not in MEMBERS and to not in ("ideas", "all"):
        sys.exit(f"받는 사람 ID가 잘못됐습니다: {to}  (가능: {', '.join(MEMBERS)}, ideas, all)")
    if to == frm:
        sys.exit("자기 자신에게는 보낼 수 없습니다.")
    if to == "ideas" and frm == "bujang":
        sys.exit("부장은 건의함을 쓰지 않습니다. 직접 결정하거나 회의를 소집하세요.")
    text = " / ".join(l.strip() for l in text.strip().splitlines() if l.strip())
    if not text:
        sys.exit("메시지가 비어 있습니다.")
    if len(text) > 400:
        sys.exit("메시지가 너무 깁니다(400자 이하). 상세 내용은 티켓 파일에 쓰고 메시지에는 티켓 번호와 요약만 쓰세요.")
    msg_id, at = str(time.time_ns()), now()
    if to == "ideas":
        recipients, shown = ["bujang"], "💡 건의: " + text
    elif to == "all":
        recipients, shown = [m for m in MEMBERS if m != frm], "📢 전원 공지: " + text
    else:
        recipients, shown = [to], text
    with Lock():
        for r in recipients:
            msg = {"msg_id": msg_id, "from": frm, "to": r, "text": shown, "at": at}
            with open(os.path.join(INBOX, f"{r}.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    log_event({"id": frm, "event": "MessageSent", "to": to, "recipients": recipients, "text": text, "at": at, "msg_id": msg_id})
    label = {"ideas": "건의함(부장)", "all": "전원"}.get(to, NAMES.get(to, to))
    print(f"접수됨: {NAMES[frm]} → {label}. 받는 사람이 대기 상태가 되면 자동으로 전달됩니다. 이제 응답을 마치세요.")


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def pane_of(role):
    try:
        pane = open(os.path.join(STATUS, f"{role}.pane")).read().strip()
    except Exception:
        return None
    r = subprocess.run(["tmux", "display-message", "-p", "-t", pane, "#{pane_id}"], capture_output=True, text=True)
    return pane if r.returncode == 0 and r.stdout.strip() == pane else None


def take_all(role, held_from=()):
    path = os.path.join(INBOX, f"{role}.jsonl")
    with Lock():
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            msgs = [json.loads(l) for l in f if l.strip()]
        take = [m for m in msgs if m.get("from") not in held_from]
        keep = [m for m in msgs if m.get("from") in held_from]
        with open(path, "w", encoding="utf-8") as f:
            for m in keep:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
    return take


def pair_key(a, b):
    return "+".join(sorted((a, b)))


def held_pairs():
    try:
        return {n[5:] for n in os.listdir(INBOX) if n.startswith("HOLD_")}
    except Exception:
        return set()


GIT_REFS = os.path.join(os.path.dirname(TEAM), "project", ".git", "refs", "heads")


def last_commit_time():
    t = 0.0
    for dp, _, fs in os.walk(GIT_REFS):
        for f in fs:
            try:
                t = max(t, os.path.getmtime(os.path.join(dp, f)))
            except OSError:
                pass
    return t


def has_mail(role):
    p = os.path.join(INBOX, f"{role}.jsonl")
    return os.path.exists(p) and os.path.getsize(p) > 0


TICKETS = os.path.join(TEAM, "tickets")


def ticket_meta(path):
    meta = {}
    try:
        with open(path, encoding="utf-8") as f:
            if f.readline().strip() != "---":
                return None
            for line in f:
                if line.strip() == "---":
                    break
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.split("#", 1)[0].strip().strip('"')
    except Exception:
        return None
    return meta


def scan_tickets():
    out = {}
    try:
        names = os.listdir(TICKETS)
    except Exception:
        return out
    for n in names:
        if n.startswith("T-") and n.endswith(".md"):
            m = ticket_meta(os.path.join(TICKETS, n))
            if m:
                out[n] = (m.get("status", "?"), m.get("assignee", "?"), m.get("title", ""), m.get("blocked", "false"))
    return out


def watch_tickets(prev):
    """반환: (현재 스냅샷, 상태 변경이 있었는지)"""
    cur = scan_tickets()
    changed = False
    for n, (st, who, title, blocked) in sorted(cur.items()):
        tid = n[:-3]
        old = prev.get(n)
        if old is None:
            ev = {"event": "TicketCreated", "ticket": tid, "status": st, "assignee": who, "title": title}
        elif old[0] != st:
            ev = {"event": "TicketStatus", "ticket": tid, "from_status": old[0], "status": st, "assignee": who, "title": title}
        elif old[3] != blocked and blocked == "true":
            ev = {"event": "TicketBlocked", "ticket": tid, "status": st, "assignee": who, "title": title}
        else:
            continue
        log_event(dict(id="ticket", at=now(), **ev))
        changed = changed or ev["event"] != "TicketBlocked"
    return cur, changed


def mailman():
    interval = float(os.environ.get("MAIL_INTERVAL", "2"))
    max_per_hour = int(os.environ.get("MAIL_MAX_PER_HOUR", "600"))
    loop_window = int(os.environ.get("MAIL_LOOP_WINDOW", "600"))
    loop_max = int(os.environ.get("MAIL_LOOP_MAX", "12"))
    pairlog = {}             # pair -> deque(전달 시각)
    last_ticket_change = time.time()
    delivered = {}           # role -> 마지막 전달 시각(ISO). 그 이후 상태가 갱신돼야 다음 전달
    history = deque()        # 전달 시각(epoch)
    paused_shown = False
    tickets = scan_tickets()   # 시작 시점 상태를 기준선으로 (과거 변경은 기록하지 않음)
    print(f"[{now()}] 우체부 근무 시작 · 간격 {interval}s · 핑퐁 감지 {loop_window // 60}분 {loop_max}회(진전 없을 때) · 안전망 시간당 {max_per_hour}회")
    print(f"           핑퐁 보류 해제: rm {INBOX}/HOLD_<a>+<b>")
    print(f"           일시정지: touch {PAUSE}   /   재개: rm {PAUSE}")
    while True:
        tickets, changed = watch_tickets(tickets)   # 일시정지 중에도 티켓 변화는 기록
        if changed:
            last_ticket_change = time.time()
        if os.path.exists(PAUSE):
            if not paused_shown:
                print(f"[{now()}] ⏸  일시정지 중 (메시지는 보관됨)")
                paused_shown = True
            time.sleep(interval)
            continue
        if paused_shown:
            print(f"[{now()}] ▶  전달 재개")
            paused_shown = False

        holds = held_pairs()
        for role in MEMBERS:
            if not has_mail(role):
                continue
            st = read_json(os.path.join(STATUS, f"{role}.json"))
            if not st or st.get("state") != "idle":
                continue
            last = delivered.get(role)
            if last and st.get("at", "") <= last:
                # 방금 넣은 메시지를 아직 처리 시작 안 한 상태 (60초 지나면 그냥 진행)
                if time.time() - datetime.fromisoformat(last).timestamp() < 60:
                    continue
            pane = pane_of(role)
            if not pane:
                continue
            t = time.time()
            while history and t - history[0] > 3600:
                history.popleft()
            if len(history) >= max_per_hour:
                with open(PAUSE, "w") as f:
                    f.write(f"{now()} 안전망: 시간당 전체 전달 {max_per_hour}회 초과로 자동 일시정지\n")
                log_event({"id": "mailman", "event": "MailPaused", "at": now(), "reason": "rate_limit"})
                print(f"[{now()}] ⛔ 시간당 상한 초과 → 자동 일시정지. 대화가 핑퐁 중인지 확인하세요.")
                break
            held_from = {p.replace(role, "").strip("+") for p in holds if role in p.split("+")}
            msgs = take_all(role, held_from)
            if not msgs:
                continue
            body = " | ".join(f"📨 {NAMES.get(m['from'], m['from'])}({m['from']}): {m['text']}" for m in msgs)
            subprocess.run(["tmux", "send-keys", "-t", pane, "-l", body])
            time.sleep(0.4)
            subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"])
            delivered[role] = now()
            history.append(t)
            for m in msgs:
                log_event({"id": m["from"], "event": "MessageDelivered", "to": role, "text": m["text"],
                           "at": delivered[role], "msg_id": m["msg_id"]})
                print(f"[{delivered[role]}] {NAMES.get(m['from'], m['from'])} → {NAMES[role]}: {m['text']}")
                # 핑퐁 감지 (직원끼리만. 사장님·회의실 메시지는 제외)
                if m["from"] in MEMBERS:
                    key = pair_key(m["from"], role)
                    dq = pairlog.setdefault(key, deque())
                    dq.append(t)
                    while dq and t - dq[0] > loop_window:
                        dq.popleft()
                    progress = max(last_ticket_change, last_commit_time())
                    if len(dq) >= loop_max and progress < dq[0] and key not in holds:
                        a, b = key.split("+")
                        with open(os.path.join(INBOX, f"HOLD_{key}"), "w") as f:
                            f.write(f"{now()} {NAMES[a]}↔{NAMES[b]} {loop_window // 60}분간 {len(dq)}회, 진전 없음\n")
                        holds.add(key)
                        log_event({"id": "mailman", "event": "MailLoop", "pair": [a, b], "count": len(dq),
                                   "window_min": loop_window // 60, "hold": f"team/inbox/HOLD_{key}", "at": now()})
                        print(f"[{now()}] ⛔ 핑퐁 감지: {NAMES[a]}↔{NAMES[b]} ({len(dq)}회, 진전 없음) → 둘 사이 전달 보류")
        time.sleep(interval)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "mailman":
        try:
            mailman()
        except KeyboardInterrupt:
            print("\n우체부 퇴근")
    elif len(sys.argv) >= 4 and sys.argv[1] == "send":
        send(sys.argv[2], " ".join(sys.argv[3:]))
    else:
        sys.exit('사용법: send.sh <받는사람ID> "<메시지>"   (ID: ' + ", ".join(MEMBERS) + ")")
