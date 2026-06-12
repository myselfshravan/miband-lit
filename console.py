#!/usr/bin/env python3
"""Live hacker-style terminal feed of heart rate + bulb colour.

Reads the shared store and streams a colourful line for every new reading and
every command sent to the band. Built for demos: point at the terminal while
your heart rate fluctuates, then at the dashboard, band, and light.

    ./venv/bin/python console.py
"""
import time
from datetime import datetime

import store
from wiz_pulse import auto_range, bpm_to_rgb

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def fg(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"


def bg(r, g, b):
    return f"\033[48;2;{r};{g};{b}m"


HEART = fg(255, 60, 60) + "♥" + RESET

BANNER = f"""{fg(0,255,140)}{BOLD}
   ███╗   ███╗██╗██████╗  █████╗ ███╗   ██╗██████╗     ██╗     ██╗████████╗
   ████╗ ████║██║██╔══██╗██╔══██╗████╗  ██║██╔══██╗    ██║     ██║╚══██╔══╝
   ██╔████╔██║██║██████╔╝███████║██╔██╗ ██║██║  ██║    ██║     ██║   ██║
   ██║╚██╔╝██║██║██╔══██╗██╔══██║██║╚██╗██║██║  ██║    ██║     ██║   ██║
   ██║ ╚═╝ ██║██║██████╔╝██║  ██║██║ ╚████║██████╔╝    ███████╗██║   ██║
   ╚═╝     ╚═╝╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝╚═════╝     ╚══════╝╚═╝   ╚═╝
{RESET}{DIM}   live heart rate  ·  Mi Band 5 → Mac → dashboard → light{RESET}
"""

STATE_LINE = {
    "scanning": (fg(255, 200, 0), "scanning for band…"),
    "connected": (fg(0, 180, 255), "connected, authenticating…"),
    "authenticated": (fg(0, 255, 140), "AUTHENTICATED · streaming"),
    "not_found": (fg(255, 80, 80), "band not found"),
    "auth_failed": (fg(255, 80, 80), "auth failed"),
    "disconnected": (fg(150, 150, 150), "disconnected"),
    "error": (fg(255, 80, 80), "error"),
}


def now_str():
    return datetime.now().strftime("%H:%M:%S")


def readings_since(ts):
    with store.get_conn() as c:
        rows = c.execute(
            "SELECT ts, bpm FROM readings WHERE ts > ? ORDER BY ts", (ts,)
        ).fetchall()
    return [(r["ts"], r["bpm"]) for r in rows]


def bar(bpm, low, high, width=18):
    t = 0.0 if high <= low else max(0.0, min(1.0, (bpm - low) / (high - low)))
    n = int(round(t * width))
    return "█" * n + "·" * (width - n)


def main():
    store.init_db()
    print(BANNER)
    print(f"{DIM}   dashboard → http://localhost:8501   ·   Ctrl-C to stop{RESET}\n")

    last_ts = time.time() - 1  # only show readings from here on
    last_bpm = None
    last_state = None
    last_cmd_id = 0
    with store.get_conn() as c:
        row = c.execute("SELECT MAX(id) AS m FROM commands").fetchone()
        if row and row["m"]:
            last_cmd_id = row["m"]

    while True:
        # Connection-state changes
        state = store.get_status("connection")
        if state and state != last_state:
            colour, label = STATE_LINE.get(state, (RESET, state))
            print(f"{DIM}{now_str()}{RESET} │ {colour}● {label}{RESET}")
            last_state = state

        # New commands sent to the band
        with store.get_conn() as c:
            crows = c.execute(
                "SELECT id, kind, payload, status FROM commands WHERE id > ? ORDER BY id",
                (last_cmd_id,),
            ).fetchall()
        import json
        for cr in crows:
            last_cmd_id = cr["id"]
            payload = json.loads(cr["payload"] or "{}")
            if cr["kind"] == "notify":
                txt = payload.get("text", "")
                print(f"{DIM}{now_str()}{RESET} │ {fg(255,0,200)}⚡ NOTIFY → band:{RESET} \"{txt}\"")
            elif cr["kind"] == "vibrate":
                print(f"{DIM}{now_str()}{RESET} │ {fg(255,160,0)}📳 VIBRATE → band{RESET}")

        # New heart-rate readings
        new = readings_since(last_ts)
        if new:
            low, high = auto_range((70, 110))
            for ts, bpm in new:
                last_ts = ts
                r, g, b = bpm_to_rgb(bpm, low, high)
                if last_bpm is None:
                    trend = f"{DIM}━{RESET}"
                elif bpm > last_bpm:
                    trend = f"{fg(255,90,90)}▲{RESET}"
                elif bpm < last_bpm:
                    trend = f"{fg(90,255,90)}▼{RESET}"
                else:
                    trend = f"{DIM}━{RESET}"
                last_bpm = bpm
                colour = fg(r, g, b)
                swatch = bg(r, g, b) + "    " + RESET
                line = (
                    f"{DIM}{datetime.fromtimestamp(ts).strftime('%H:%M:%S')}{RESET} │ "
                    f"{HEART} {colour}{BOLD}{bpm:3d} BPM{RESET} {trend} │ "
                    f"{colour}{bar(bpm, low, high)}{RESET} │ "
                    f"{swatch} {colour}rgb({r:3d},{g:3d},{b:3d}){RESET} "
                    f"{DIM}[{int(low)}-{int(high)}]{RESET}"
                )
                print(line)
        time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{DIM}stopped.{RESET}")
