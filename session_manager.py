import time
import json
from datetime import datetime, timedelta
from pathlib import Path
from constants import MAXIMUM_PLAYTIME_INT, FREEPLAY_DAYS

SESSION_FILE = Path("sessions.json")
PLAY_LIMIT = timedelta(hours=MAXIMUM_PLAYTIME_INT)  # normal weekday limit

sessions = {}
unlimited_play_announced = False  # global weekend announcement flag
first_cycle = True  # Track if this is the first cycle after startup

# If it is saturday or sunday. Change this condition for your own use-case
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
                "rollover_time": 0,  # unused time from previous days
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
    global unlimited_play_announced, first_cycle
    load_sessions()

    # Handle first cycle after program restart
    if first_cycle:
        now_str = dt_to_iso(datetime.now())
        for player, data in sessions.items():
            # Reset online status to prevent phantom time from restart
            data["online"] = False
            # Update last_checked to current time to prevent delta issues
            data["last_checked"] = now_str
        save_sessions()
        first_cycle = False
    now = datetime.now()
    today_str = now.date().isoformat()
    online_players = get_online_players()
    weekday = now.weekday()
    is_freeplay = FREEPLAY_DAYS[weekday]

    # --- Daily reset for ALL players (including offline ones) ---
    for player, data in sessions.items():
        if data.get("session_date") != today_str:
            # Calculate unused time and add to rollover (but not on freeplay periods)
            yesterday_weekday = (now - timedelta(days=1)).weekday()
            if yesterday_weekday < 5:  # only rollover from weekdays
                current_rollover = data.get("rollover_time", 0)
                yesterday_playtime = data["playtime"]
                unused_time = max(0, PLAY_LIMIT.total_seconds() - yesterday_playtime)

                # Clear rollover if today is Saturday (after Friday)
                if weekday == 5:  # Saturday
                    data["rollover_time"] = 0
                    if unused_time > 0:
                        unused_hours = unused_time / 3600
                        # Only send message if player is online
                        if player in online_players:
                            send_message(player, f"Note: {unused_hours:.1f} hours of unused time expired entering the weekend.")
                else:
                    data["rollover_time"] = current_rollover + unused_time
                    if unused_time > 0:
                        unused_hours = unused_time / 3600
                        total_rollover_hours = (current_rollover + unused_time) / 3600
                        # Only send messagfe if player is online
                        if player in online_players:
                            send_message(player, f"You had {unused_hours:.1f} hours of unused time yesterday. Total rollover: {total_rollover_hours:.1f} hours.")
            else:
                # Don't rollover weekend time, but keep existing rollover
                data["rollover_time"] = data.get("rollover_time", 0)

            # Reset session data for the new day
            data["session_start"] = dt_to_iso(now)
            data["playtime"] = 0
            data["session_date"] = today_str
            data["last_checked"] = dt_to_iso(now)
            data["online"] = False
            for k in data["announcements"]:
                data["announcements"][k] = False

            # Unban ALL players on daily reset
            if data.get("banned"):
                run_command(f"pardon {player}")
                data["banned"] = False
                send_message(None, f"{player} has been unbanned for the new day.")

    # --- Handle freeplay unlimited logic ---
    if is_freeplay and not unlimited_play_announced:
        send_message(None, "Weekend unlimited playtime has started! Enjoy!")
        run_command("/title @a title {{\"text\":\"Its the weekend! Unlimited Playtime!\",\"color\":\"green\",\"bold\":true}}")
        unlimited_play_announced = True
    elif not is_freeplay and unlimited_play_announced:
        send_message(None, "Weekend unlimited playtime has ended. Weekday limit resumed! Resetting all session times.")
        run_command("/title @a title {{\"text\":\"Weekend Unlimited Playtime ENDED\",\"color\":\"red\",\"bold\":true}}")
        unlimited_play_announced = False

        # Reset all players for weekday start, but preserve online status to prevent delta issues
        for player, data in sessions.items():
            data["playtime"] = 0
            data["rollover_time"] = 0  # clear rollover when weekend ends
            data["session_start"] = dt_to_iso(now)
            # Don't set online = False here - preserve current online status to prevent phantom deltas
            data["last_checked"] = dt_to_iso(now)  # Reset last_checked to now to prevent large deltas
            data["banned"] = False
            for k in data["announcements"]:
                data["announcements"][k] = False
            run_command(f"pardon {player}")

    # --- Handle player sessions ---
    load_sessions()
    for player in online_players:
        if player in sessions:
            # Daily reset is now handled globally above for all players
            # Don't set online status here - it will be set after checking was_online
            pass
        else:
            sessions[player] = {
                "session_start": dt_to_iso(now),
                "playtime": 0,
                "rollover_time": 0,
                "online": False,  # Start as offline so first login detection works
                "session_date": today_str,
                "banned": False,
                "announcements": {k: False for k in ["1min", "5min", "10min", "15min", "30min"]}
            }

        # Detect first login (transition from offline to online)
        was_online = sessions[player].get("online", False)
        sessions[player]["online"] = True  # Set online status for this cycle

        if was_online:
            # Already online, calculate and update playtime
            last_checked = iso_to_dt(sessions[player].get("last_checked", dt_to_iso(now)))
            delta = (now - last_checked).total_seconds()
            
            # Protect against large deltas (more than 2 minutes suggests timing issues)
            if delta > 120:
                print(f"[WARNING] Large delta detected for {player}: {delta}s, capping to 60s")
                delta = 60
            elif delta < 0:
                print(f"[WARNING] Negative delta detected for {player}: {delta}s, setting to 0")
                delta = 0
            
            # Only check for ban evading on weekdays (weekends have no restrictions)
            if not is_freeplay and sessions[player]["banned"]:
                print([f"{player} is BAN EVADING!"])
                run_command(f"ban {player} really? thought you could get away with it that easily?")
            else:
                # Only add delta if it's reasonable (positive and not too large)
                if delta > 0:
                    sessions[player]["playtime"] += delta
        else:
            # First login, don't add any delta time
            print(f"[INFO] {player} logging in for first time today")
            if not is_freeplay:
                rollover_time = sessions[player].get("rollover_time", 0)
                total_limit = PLAY_LIMIT.total_seconds() + rollover_time
                # Ensure playtime is never negative
                current_playtime = max(0, sessions[player]["playtime"])
                sessions[player]["playtime"] = current_playtime
                seconds_remaining = total_limit - current_playtime
                pretty_time_str = str(timedelta(seconds=int(max(0, seconds_remaining))))
                if seconds_remaining <= 0 or sessions[player]["banned"] is True:
                    send_message(player, "You are not welcome. Please come back tomorrow")
                else:
                    welcome_msg = f"Welcome! Playtime tracking has started. You have {pretty_time_str} remaining today."
                    if rollover_time > 0:
                        rollover_hours = rollover_time / 3600
                        welcome_msg += f" (includes {rollover_hours:.1f} hours carried over from previous days)"
                    send_message(player, welcome_msg)
            else:
                send_message(player, "Welcome! Its the weekend, there are currently no playtime restrictions")

        sessions[player]["last_checked"] = dt_to_iso(now)

    # Mark offline players
    for player in list(sessions.keys()):
        if player not in online_players:
            sessions[player]["online"] = False

    # --- Enforce weekday limits ---
    if not is_freeplay:
        for player, data in sessions.items():
            rollover_time = data.get("rollover_time", 0)
            total_limit = PLAY_LIMIT.total_seconds() + rollover_time
            remaining = total_limit - data["playtime"]
            base_hours = PLAY_LIMIT.total_seconds() // 3600
            if rollover_time > 0:
                print(f"[{player}] Base limit: {PLAY_LIMIT}, Rollover: {timedelta(seconds=rollover_time)}, Total limit: {timedelta(seconds=total_limit)}, Time remaining: {timedelta(seconds=max(0, remaining))}")
            else:
                print(f"[{player}] Max playtime: {PLAY_LIMIT}, Time remaining: {timedelta(seconds=max(0, remaining))}")
            time_limit_text = f"{int(base_hours)}-hour limit" + (f" (+{rollover_time/3600:.1f}h rollover)" if rollover_time > 0 else "")

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
                    run_command(f"/title {player} title {{\"text\":\"{pretty_time(remaining)} Remaining!\",\"color\":\"red\",\"bold\":true}}")
                    data["announcements"][label] = True
                    break

            # Ban and reset - ensure playtime is never negative before checking
            data["playtime"] = max(0, data["playtime"])
            rollover_time = data.get("rollover_time", 0)
            total_limit = PLAY_LIMIT.total_seconds() + rollover_time
            if data["playtime"] >= total_limit and not data.get("banned", False):
                base_hours = PLAY_LIMIT.total_seconds() // 3600
                limit_msg = f"{base_hours}-hour"
                if rollover_time > 0:
                    limit_msg += f" (+{rollover_time/3600:.1f}h rollover)"
                send_message(None, f"{player} has reached the {limit_msg} playtime limit! See you tomorrow buddy")
                run_command(f"/title {player} title {{\"text\":\"BYE BYE\",\"color\":\"red\",\"bold\":true}}")
                run_command(f"ban {player} Reached playtime limit. Resets at midnight")
                data["banned"] = True
                data["session_start"] = dt_to_iso(now)
                data["playtime"] = 0
                data["last_checked"] = dt_to_iso(now)  # Update last_checked to prevent phantom time
                data["online"] = False
                for k in data["announcements"]:
                    data["announcements"][k] = False

    save_sessions()
    time.sleep(60)  # pause until next cycle
