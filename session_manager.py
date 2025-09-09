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
                # Unused time gets rolled over to the next day
                # delta_remaining = PLAY_LIMIT.total_seconds() - data["playtime"]
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

        # Detect first login (transition from offline to online)
        was_online = sessions[player].get("online", False)
        sessions[player]["online"] = True  # Set online status for this cycle
        last_checked = iso_to_dt(sessions[player].get("last_checked", dt_to_iso(now)))
        delta = (now - last_checked).total_seconds()
        if was_online:
            # Already online, just update playtime
            if sessions[player]["banned"]:
                print([f"{player} is BAN EVADING!"])
                run_command(f"ban {player} really? thought you could get away with it that easily?")
            else:
                sessions[player]["playtime"] += delta
        else:
            # First login, send welcome message
            if not is_weekend:
                seconds_remaining = PLAY_LIMIT.total_seconds() - sessions[player]["playtime"]
                pretty_time_str = str(timedelta(seconds=int(max(0, seconds_remaining))))
                if seconds_remaining <= 0 or sessions[player]["banned"] is True:
                    send_message(player, "You are not welcome. Please come back tomorrow")
                send_message(player, f"Welcome! Playtime tracking has started. You have {pretty_time_str} remaining today.")
            else:
                send_message(player, "Welcome! Its the weekend, there are currently no playtime restrictions")

        sessions[player]["last_checked"] = dt_to_iso(now)

    # Mark offline players
    for player in list(sessions.keys()):
        if player not in online_players:
            sessions[player]["online"] = False

    # --- Enforce weekday limits ---
    if not is_weekend:
        for player, data in sessions.items():
            remaining = PLAY_LIMIT.total_seconds() - data["playtime"]
            print(f"[{player}] Max playtime: {PLAY_LIMIT}, Time remaining: {timedelta(seconds=max(0, remaining))}")
            time_limit_hours = PLAY_LIMIT.total_seconds() // 3600
            time_limit_text = f"{int(time_limit_hours)}-hour limit"

            def pretty_time(seconds):
                td = timedelta(seconds=int(max(0, seconds)))
                parts = []
                if td.days > 0:
                    parts.append(f"{td.days}d")
                hours, rem = divmod(td.seconds, 3600)
                if hours > 0:
                    parts.append(f"{hours}h")
                minutes, seconds = divmod(rem, 60)
                if minutes > 0:
                    parts.append(f"{minutes}m")
                if seconds > 0 and not parts:
                    parts.append(f"{seconds}s")
                return " ".join(parts) if parts else "0s"

            thresholds = [
                (60, "1min"),
                (300, "5min"),
                (600, "10min"),
                (900, "15min"),
                (1800, "30min"),
            ]
            for threshold, label in thresholds:
                if remaining <= threshold and not data["announcements"][label]:
                    send_message(
                        None,
                        f"{player} has {pretty_time(remaining)} left before reaching the {time_limit_text}!"
                    )
                    data["announcements"][label] = True
                    break

            # Ban and reset
            if data["playtime"] >= PLAY_LIMIT.total_seconds() and not data.get("banned", False):
                time_limit_hours = PLAY_LIMIT.total_seconds() // 3600
                send_message(None, f"{player} has reached the {time_limit_hours}-hour playtime limit! See you tomorrow buddy")
                run_command(f"ban {player} Reached {time_limit_hours}-hour limit. Resets at midnight")
                data["banned"] = True
                data["session_start"] = dt_to_iso(now)
                data["playtime"] = 0
                data["online"] = False
                for k in data["announcements"]:
                    data["announcements"][k] = False

    save_sessions()
    time.sleep(5)  # pause until next cycle
