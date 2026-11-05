#!/usr/bin/env python3
"""팀 채팅창 (읽기 전용 뷰어).

team/status/events.jsonl 을 실시간으로 읽어서 직원 간 메시지, 건의, 회의 발언, 티켓 상태 변경을
채팅 형식으로 보여주고, 맨 아래에 직원 상태 표시줄을 그린다.
"""
import json, os, shutil, sys, time, unicodedata

TEAM = os.environ.get("TEAM_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENTS = os.path.join(TEAM, "status", "events.jsonl")
STATUS = os.path.join(TEAM, "status")
PAUSE = os.path.join(TEAM, "inbox", "PAUSE")

ORDER = ["bujang", "chajang", "gwajang", "daeri-a", "daeri-b", "sawon"]
NAMES = {"bujang": "부장", "chajang": "차장", "gwajang": "과장", "daeri-a": "대리A", "daeri-b": "대리B",
         "sawon": "사원", "boss": "사장님", "meeting": "회의실", "ideas": "💡건의함", "all": "📢전체"}
COLOR = {"bujang": 220, "chajang": 45, "gwajang": 171, "daeri-a": 114, "daeri-b": 75, "sawon": 209,
         "boss": 231, "meeting": 250}
DIM, RST, BOLD = "\x1b[2m", "\x1b[0m", "\x1b[1m"
ICON = {"working": "🟢", "idle": "⚪", "waiting": "🟡", "offline": "⚫"}


def c(who, text, bold=True):
    col = COLOR.get(who)
    return (f"{BOLD if bold else ''}\x1b[38;5;{col}m{text}{RST}") if col else text


def name(who):
    return c(who, NAMES.get(who, who))


def cw(ch):
    if unicodedata.combining(ch) or ch in "‍️":
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) >= 0x1F300:
        return 2
    return 1


def wrap(text, width, indent=4):
    """동아시아 문자 폭을 고려한 줄바꿈. 반환: 줄 목록(들여쓰기 포함)"""
    width = max(10, width - indent)
    out, cur, w = [], "", 0
    for ch in text:
        x = cw(ch)
        if w + x > width:
            out.append(cur)
            cur, w = "", 0
            if ch == " ":
                continue
        cur += ch
        w += x
    if cur:
        out.append(cur)
    return [" " * indent + l for l in out] or [" " * indent]


def hhmm(at):
    return at[11:16] if len(at) >= 16 else at


class Chat:
    def __init__(self):
        self.entries = []      # dict(kind, ...)
        self.by_msg = {}       # msg_id -> entry
        self.offset = 0

    def feed(self):
        try:
            size = os.path.getsize(EVENTS)
        except OSError:
            return False
        if size < self.offset:          # 파일이 새로 만들어짐
            self.__init__()
        if size == self.offset:
            return False
        with open(EVENTS, encoding="utf-8") as f:
            f.seek(self.offset)
            data = f.read()
            self.offset = f.tell()
        for line in data.splitlines():
            try:
                self.add(json.loads(line))
            except Exception:
                pass
        self.entries = self.entries[-400:]
        return True

    def add(self, r):
        ev = r.get("event", "")
        if ev == "MessageSent":
            e = {"kind": "msg", "r": r, "need": len(r.get("recipients") or [r.get("to")]), "got": 0}
            self.entries.append(e)
            self.by_msg[r.get("msg_id")] = e
        elif ev == "MessageDelivered":
            e = self.by_msg.get(r.get("msg_id"))
            if e:
                e["got"] += 1
        elif ev in ("MeetingStart", "MeetingSay", "MeetingEnd", "TicketCreated", "TicketStatus",
                    "TicketBlocked", "MailPaused", "MailLoop"):
            self.entries.append({"kind": ev, "r": r})

    def render_entry(self, e, width):
        r = e["r"]
        k = e["kind"]
        if k == "msg":
            frm, to = r.get("id"), r.get("to")
            mark = (f"{DIM}✓{RST}" if e["got"] >= e["need"] else f"{DIM}⏳{RST}") if e["need"] == 1 \
                else f"{DIM}✓{e['got']}/{e['need']}{RST}"
            head = f"{DIM}{hhmm(r['at'])}{RST} {name(frm)} {DIM}→{RST} {name(to)}  {mark}"
            return [head] + wrap(r.get("text", ""), width, 4)
        if k == "MeetingStart":
            who = ", ".join(NAMES.get(a, a) for a in r.get("attendees", []))
            return [f"{DIM}{hhmm(r['at'])}{RST} 🏛  {BOLD}회의 {r['meeting']} 시작{RST} {DIM}· {who}{RST}"] + \
                   [f"{DIM}{l}{RST}" for l in wrap(r.get("topic", ""), width, 4)]
        if k == "MeetingSay":
            return [f"   🗣  {name(r['id'])} {DIM}R{r.get('round')}{RST}"] + wrap(r.get("text", ""), width, 6)
        if k == "MeetingEnd":
            return [f"{DIM}{hhmm(r['at'])}{RST} 🏛  {BOLD}회의 {r['meeting']} 종료{RST} "
                    f"{DIM}· 발언 {r.get('statements')}회 → {r.get('file')}{RST}"]
        who = NAMES.get(r.get("assignee"), r.get("assignee", ""))
        if k == "TicketCreated":
            return [f"{DIM}{hhmm(r['at'])} 📝 {r['ticket']} 생성 · {r.get('title', '')[:40]} ({who}){RST}"]
        if k == "TicketStatus":
            return [f"{DIM}{hhmm(r['at'])}{RST} 🔄 {BOLD}{r['ticket']}{RST} {DIM}{r.get('from_status')} →{RST} "
                    f"{BOLD}{r.get('status')}{RST} {DIM}· {who}{RST}"]
        if k == "TicketBlocked":
            return [f"{DIM}{hhmm(r['at'])}{RST} 🚧 {BOLD}{r['ticket']} 막힘{RST} {DIM}· {who}{RST}"]
        if k == "MailPaused":
            return [f"{hhmm(r['at'])} ⛔ {BOLD}우체부 전체 일시정지 (안전망: 시간당 상한 초과){RST}"]
        if k == "MailLoop":
            a, b = r.get("pair", ["?", "?"])
            return [f"{hhmm(r['at'])} ⛔ {BOLD}핑퐁 감지{RST} {name(a)}↔{name(b)} "
                    f"{DIM}({r.get('window_min')}분 {r.get('count')}회, 진전 없음) → 둘 사이만 전달 보류{RST}",
                    f"    {DIM}해제: rm {r.get('hold')}{RST}"]
        return []


def status_lines(width):
    icons, details = [], []
    for m in ORDER:
        try:
            s = json.load(open(os.path.join(STATUS, f"{m}.json"), encoding="utf-8"))
        except Exception:
            s = {}
        st = s.get("state", "")
        icons.append(f"{ICON.get(st, '·')}{c(m, NAMES[m], bold=False)}")
        if st == "working":
            what = s.get("tool") or s.get("activity", "")
            tgt = os.path.basename(str(s.get("target", ""))) if s.get("tool") in ("Edit", "Write", "Read") \
                else str(s.get("target", "") or s.get("detail", ""))
            details.append(f"{c(m, NAMES[m], bold=False)} {DIM}{what} {tgt}{RST}")
        elif st == "waiting":
            details.append(f"{c(m, NAMES[m], bold=False)} 🟡 {BOLD}사장님 확인 대기{RST} {DIM}(작업실에서 확인){RST}")
    out = [" ".join(icons)]
    try:
        for n in sorted(os.listdir(os.path.dirname(PAUSE))):
            if n.startswith("HOLD_"):
                a, b = n[5:].split("+")
                out.append(f"⛔ {NAMES.get(a, a)}↔{NAMES.get(b, b)} 전달 보류 중 {DIM}(rm team/inbox/{n}){RST}")
    except Exception:
        pass
    if os.path.exists(PAUSE):
        out.append(f"⏸  {BOLD}우체부 일시정지 중{RST} {DIM}(rm team/inbox/PAUSE 로 재개){RST}")
    for d in details:
        out.append(trunc(d, width))
    return out


def trunc(s, width):
    """ANSI 코드를 보존하면서 표시 폭 기준으로 자르기"""
    out, w, i = "", 0, 0
    while i < len(s):
        if s[i] == "\x1b":
            j = s.find("m", i)
            out += s[i:j + 1]
            i = j + 1
            continue
        x = cw(s[i])
        if w + x > width - 1:
            return out + "…" + RST
        out += s[i]
        w += x
        i += 1
    return out


def main():
    chat = Chat()
    last_sig = None
    sys.stdout.write("\x1b[?25l")   # 커서 숨김
    try:
        while True:
            changed = chat.feed()
            try:
                cols, rows = os.get_terminal_size(sys.stdout.fileno())   # 환경변수 COLUMNS 무시, 실제 칸 크기
            except OSError:
                cols, rows = shutil.get_terminal_size((80, 24))
            try:
                smt = max(os.path.getmtime(os.path.join(STATUS, f)) for f in os.listdir(STATUS) if f.endswith(".json"))
            except Exception:
                smt = 0
            sig = (chat.offset, cols, rows, smt, os.path.exists(PAUSE), sum(e.get("got", 0) for e in chat.entries[-50:]))
            if sig != last_sig:
                last_sig = sig
                strip = status_lines(cols)
                body_h = max(3, rows - len(strip) - 3)
                lines = []
                for e in chat.entries:
                    lines.extend(chat.render_entry(e, cols))
                if not lines:
                    lines = [f"{DIM}아직 대화가 없습니다. 직원들이 send.sh 로 메시지를 보내면 여기에 표시됩니다.{RST}"]
                lines = lines[-body_h:]
                buf = ["\x1b[H\x1b[2J", f"{BOLD}💬 팀 채팅{RST} {DIM}· 읽기 전용 · Ctrl+b 1 작업실 · Ctrl+b 2 우체부{RST}", ""]
                buf += [trunc(l, cols) for l in lines]
                buf += [""] * (body_h - len(lines))
                buf += [f"{DIM}{'─' * (cols - 1)}{RST}"] + strip
                sys.stdout.write("\n".join(buf))
                sys.stdout.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?25h\n")


if __name__ == "__main__":
    main()
