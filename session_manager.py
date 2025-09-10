import time
import json
from datetime import datetime, timedelta
from pathlib import Path

SESSION_FILE = Path("sessions.json")
PLAY_LIMIT = timedelta(hours=3)  # normal weekday limit

sessions = {}
weekend_unlimited_announced = False  # global weekend announcement flag


def load_sessions():
    global sessions
    if SESSION_FILE.exists():
        with open(SESSION_FILE, "r") as f:
            sessions = json.load(f)
    else:
        sessions = {}


def save_sessions():
    with open(SESSION_FILE, "w") as f:
        json.dump(sessions, f, indent=2)


def dt_to_iso(dt):
    return dt.isoformat()


def iso_to_dt(iso_str):
    return datetime.fromisoformat(iso_str)


def initialize_players(player_list):
    """Add players from initial list to sessions."""
    load_sessions()
    now_str = dt_to_iso(datetime.now())
    today_str = datetime.now().date().isoformat()
    for player in player_list:
        if player not in sessions:
            sessions[player] = {
                "session_start": now_str,
                "playtime": 0,
                "online": True,
                "session_date": today_str,
                "banned": False,
                "announcements": {k: False for k in ["1min", "5min", "10min", "15min", "30min"]}
            }
    save_sessions()


def session_cycle(get_online_players=None, send_message=None, run_command=None):
    """
    One cycle of session management (called repeatedly while server is online).
    Pauses automatically when server is offline because `main` controls execution.
    """
    global weekend_unlimited_announced
    load_sessions()

    if get_online_players is None:
        get_online_players = lambda: []

    if send_message is None:
        send_message = lambda player, msg: print(f"{player or 'ALL'}: {msg}")

    if run_command is None:
        run_command = lambda cmd: None

    now = datetime.now()
    today_str = now.date().isoformat()
    online_players = get_online_players()
    weekday = now.weekday()
    is_weekend = weekday >= 5  # Saturday=5, Sunday=6

    # --- Handle weekend unlimited logic ---
    if is_weekend and not weekend_unlimited_announced:
        send_message(None, "Weekend unlimited playtime has started! Enjoy!")
        weekend_unlimited_announced = True
    elif not is_weekend and weekend_unlimited_announced:
        send_message(None, "Weekend unlimited playtime has ended. Weekday limit resumed! Resetting all session times.")
        weekend_unlimited_announced = False

        for player, data in sessions.items():
            data["playtime"] = 0
            data["session_start"] = dt_to_iso(now)
            data["online"] = True
            data["banned"] = False
            for k in data["announcements"]:
                data["announcements"][k] = False
            run_command(f"pardon {player}")

    # --- Handle player sessions ---
    for player in online_players:
        if player in sessions:
            # Daily reset
            if sessions[player].get("session_date") != today_str:
                sessions[player]["session_start"] = dt_to_iso(now)
                sessions[player]["playtime"] = 0
                sessions[player]["online"] = True
                sessions[player]["session_date"] = today_str
                for k in sessions[player]["announcements"]:
                    sessions[player]["announcements"][k] = False
                if sessions[player].get("banned"):
                    run_command(f"pardon {player}")
                    sessions[player]["banned"] = False
                    send_message(None, f"{player} is now unbanned and session reset for a new day.")
        else:
            sessions[player] = {
                "session_start": dt_to_iso(now),
                "playtime": 0,
                "online": True,
                "session_date": today_str,
                "banned": False,
                "announcements": {k: False for k in ["1min", "5min", "10min", "15min", "30min"]}
            }

        # Update playtime (only while online!)
        last_checked = iso_to_dt(sessions[player].get("last_checked", dt_to_iso(now)))
        delta = (now - last_checked).total_seconds()
        if sessions[player].get("online", False):
            sessions[player]["playtime"] += delta
        sessions[player]["online"] = True
        sessions[player]["last_checked"] = dt_to_iso(now)

    # Mark offline players
    for player in list(sessions.keys()):
        if player not in online_players:
            sessions[player]["online"] = False

    # --- Enforce weekday limits ---
    if not is_weekend:
        for player, data in sessions.items():
            remaining = PLAY_LIMIT.total_seconds() - data["playtime"]

            # Announcements
            if remaining <= 60 and not data["announcements"]["1min"]:
                send_message(None, f"{player} has 1 minute left before reaching the 3-hour limit!")
                data["announcements"]["1min"] = True
            elif remaining <= 300 and not data["announcements"]["5min"]:
                send_message(None, f"{player} has around 5 minutes left before reaching the 3-hour limit!")
                data["announcements"]["5min"] = True
            elif remaining <= 600 and not data["announcements"]["10min"]:
                send_message(None, f"{player} has around 10 minutes left before reaching the 3-hour limit!")
                data["announcements"]["10min"] = True
            elif remaining <= 900 and not data["announcements"]["15min"]:
                send_message(None, f"{player} has around 15 minutes left before reaching the 3-hour limit!")
                data["announcements"]["15min"] = True
            elif remaining <= 1800 and not data["announcements"]["30min"]:
                send_message(None, f"{player} has around 30 minutes left before reaching the 3-hour limit!")
                data["announcements"]["30min"] = True

            # Ban and reset
            if data["playtime"] >= PLAY_LIMIT.total_seconds() and not data.get("banned", False):
                send_message(None, f"{player} has reached the 3-hour limit! Banning and resetting session.")
                run_command(f"ban {player} Reached 3-hour limit")
                data["banned"] = True
                data["session_start"] = dt_to_iso(now)
                data["playtime"] = 0
                data["online"] = False
                for k in data["announcements"]:
                    data["announcements"][k] = False

    save_sessions()
    time.sleep(60)  # pause until next cycle
