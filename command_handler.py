import re
from datetime import datetime, timedelta
import session_manager
import json
from pathlib import Path


class CommandHandler:
    """Handles chat commands from players"""

    def __init__(self, send_command_func):
        """
        Initialize command handler

        Args:
            send_command_func: Function to send commands to the server
        """
        self.send_command = send_command_func
        self.commands = {}

        # Load admin list from file
        self.admins = self.load_admins()

        # Chat message pattern: [HH:MM:SS] [Server thread/INFO]: <username> message
        self.chat_pattern = re.compile(
            r'\[(\d{2}:\d{2}:\d{2})\] \[.*?/INFO\]: <([^>]+)> (.+)'
        )

        # Register default commands
        self._register_commands()

    def load_admins(self):
        """Load admin usernames from JSON file"""
        admin_file = Path("admins.json")
        if admin_file.exists():
            try:
                with open(admin_file, "r") as f:
                    data = json.load(f)
                    admins = data.get("admins", [])
                    print(f"[ADMIN] Loaded {len(admins)} admin(s): {', '.join(admins)}")
                    return admins
            except Exception as e:
                print(f"[ERROR] Failed to load admins.json: {e}")
                return []
        else:
            print("[WARNING] admins.json not found. No admins configured.")
            return []

    def _register_commands(self):
        """Register available commands"""
        self.commands = {
            'help': self.cmd_help,
            'playtime': self.cmd_playtime,
            'rollover': self.cmd_rollover,
            'stats': self.cmd_stats,
            'rules': self.cmd_rules,
            # Admin commands
            'unban': self.cmd_unban,
            'addtime': self.cmd_addtime,
            'resettime': self.cmd_resettime,
            'adminhelp': self.cmd_adminhelp,
        }
        print(f"[COMMANDS] Registered {len(self.commands)} commands")

    def process_console_line(self, line):
        """
        Process a console line and check for commands

        Args:
            line: Raw console line from server
        """
        match = self.chat_pattern.match(line)
        if match:
            timestamp, username, message = match.groups()
            print(f"[CHAT] {username}: {message}")

            # Check if message is a command (starts with !)
            if message.startswith('!'):
                self.handle_command(username, message)

    def handle_command(self, username, message):
        """
        Handle a command from a player

        Args:
            username: Player who sent the command
            message: The full message including the ! prefix
        """
        # Parse command and arguments
        parts = message[1:].split()  # Remove ! and split
        if not parts:
            return

        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        print(f"[COMMAND] {username} executed: !{command} {' '.join(args)}")

        # Execute command if it exists
        if command in self.commands:
            try:
                self.commands[command](username, args)
            except Exception as e:
                print(f"[ERROR] Command handler error for {command}: {e}")
                self.send_command(f"tell {username} Error executing command: {str(e)}")
        else:
            self.send_command(f"tell {username} Unknown command: !{command}. Type !help for available commands.")

    def is_admin(self, username):
        """Check if a user is an admin"""
        return username in self.admins

    # Command implementations

    def cmd_help(self, username, args):
        """Help command - shows available commands"""
        # Filter out admin commands for non-admins
        if self.is_admin(username):
            available_commands = ", ".join([f"!{cmd}" for cmd in sorted(self.commands.keys())])
            extra_msg = " (Admin commands included)"
        else:
            non_admin_cmds = ['help', 'playtime', 'rollover', 'stats', 'rules']
            available_commands = ", ".join([f"!{cmd}" for cmd in sorted(non_admin_cmds)])
            extra_msg = ""

        tellraw_json = {
            "text": "",
            "extra": [
                {"text": f"[{username}] ", "color": "gray"},
                {"text": f"Available commands{extra_msg}: ", "color": "white"},
                {"text": available_commands, "color": "aqua", "bold": True}
            ]
        }
        self.send_command(f'tellraw {username} {json.dumps(tellraw_json)}')
        print(f"[RESPONSE] Sent help response to {username}")


    def cmd_playtime(self, username, args):
        """Playtime command - shows remaining playtime for a player"""
        session_manager.load_sessions()
        sessions = session_manager.sessions

        target_player = args[0] if args else username

        if target_player in sessions:
            data = sessions[target_player]
            weekday = datetime.now().weekday()
            is_weekend = weekday >= 5

            if is_weekend:
                msg = f"{target_player} has unlimited playtime (weekend)" if target_player != username else "You have unlimited playtime (weekend)"
                color = "green"
            else:
                rollover_time = data.get("rollover_time", 0)
                total_limit = session_manager.PLAY_LIMIT.total_seconds() + rollover_time
                remaining = total_limit - data["playtime"]

                if remaining <= 0:
                    msg = f"{target_player} has no time remaining today" if target_player != username else "You have no time remaining today. Come back tomorrow!"
                    color = "red"
                else:
                    hours = int(remaining // 3600)
                    minutes = int((remaining % 3600) // 60)
                    if target_player == username:
                        msg = f"You have {hours}h {minutes}m remaining today"
                        if rollover_time > 0:
                            msg += f" (includes {rollover_time/3600:.1f}h rollover)"
                    else:
                        msg = f"{target_player} has {hours}h {minutes}m remaining today"
                    color = "gold"
        else:
            msg = f"No session data found for {target_player}" if target_player != username else "No session data found. Play for a bit first!"
            color = "red"

        tellraw_json = {
            "text": "",
            "extra": [
                {"text": f"[{username}] ", "color": "gray"},
                {"text": msg, "color": color, "bold": True}
            ]
        }
        self.send_command(f'tellraw @a {json.dumps(tellraw_json)}')
        print(f"[RESPONSE] Sent playtime info to {username}")

    def cmd_rollover(self, username, args):
        """Rollover command - shows rollover hours for a player"""
        session_manager.load_sessions()
        sessions = session_manager.sessions

        # Check if querying for another player (if args provided)
        target_player = args[0] if args else username

        if target_player in sessions:
            rollover_time = sessions[target_player].get("rollover_time", 0)
            if rollover_time > 0:
                hours = rollover_time / 3600
                if target_player == username:
                    msg = f"You have {hours:.1f} hours of rollover time"
                else:
                    msg = f"{target_player} has {hours:.1f} hours of rollover time"
                color = "aqua"
            else:
                if target_player == username:
                    msg = "You have no rollover time"
                else:
                    msg = f"{target_player} has no rollover time"
                color = "yellow"
        else:
            if target_player == username:
                msg = "No session data found"
            else:
                msg = f"No session data found for {target_player}"
            color = "red"

        tellraw_json = {
            "text": "",
            "extra": [
                {"text": f"[{username}] ", "color": "gray"},
                {"text": msg, "color": color, "bold": True}
            ]
        }
        self.send_command(f'tellraw @a {json.dumps(tellraw_json)}')
        print(f"[RESPONSE] Sent rollover info to {username}")

    def cmd_stats(self, username, args):
        """Stats command - shows server statistics"""
        session_manager.load_sessions()
        sessions = session_manager.sessions

        total_players = len(sessions)
        online_count = sum(1 for s in sessions.values() if s.get("online", False))
        banned_count = sum(1 for s in sessions.values() if s.get("banned", False))

        # Calculate average playtime
        total_playtime = sum(s.get("playtime", 0) for s in sessions.values())
        average_hours = (total_playtime / total_players) / 3600 if total_players > 0 else 0

        # Construct a fancy tellraw JSON message
        tellraw_json = {
            "text": "",
            "extra": [
                {"text": f"[{username}] ", "color": "gray"},
                {"text": "Server Stats: ", "color": "white"},
                {"text": f"{online_count} online", "color": "green", "bold": True},
                {"text": ", ", "color": "white"},
                {"text": f"{total_players} total tracked", "color": "aqua"},
                {"text": ", ", "color": "white"},
                {"text": f"{banned_count} banned", "color": "red", "bold": True},
                {"text": ", ", "color": "white"},
                {"text": f"{average_hours:.1f}h avg playtime", "color": "gold"}
            ]
        }

        # Send to everyone
        self.send_command(f'tellraw @a {json.dumps(tellraw_json)}')
        print(f"[RESPONSE] Sent stats to {username}")

    def cmd_rules(self, username, args):
        """Rules command - shows server playtime rules"""
        weekday = datetime.now().weekday()
        is_weekend = weekday >= 5

        if is_weekend:
            tellraw_json = {
                "text": "",
                "extra": [
                    {"text": f"[{username}] ", "color": "gray"},
                    {"text": "Weekend Mode Active! ", "color": "green", "bold": True},
                    {"text": "Unlimited playtime. ", "color": "aqua"},
                    {"text": "Weekday limit: ", "color": "white"},
                    {"text": "3 hours ", "color": "gold", "bold": True},
                    {"text": "(unused time rolls over)", "color": "yellow"}
                ]
            }
        else:
            tellraw_json = {
                "text": "",
                "extra": [
                    {"text": f"[{username}] ", "color": "gray"},
                    {"text": "Weekday Rules: ", "color": "yellow", "bold": True},
                    {"text": "3 hour daily limit. ", "color": "gold"},
                    {"text": "Unused time rolls over. ", "color": "aqua"},
                    {"text": "Weekends have ", "color": "white"},
                    {"text": "unlimited playtime!", "color": "green", "bold": True}
                ]
            }

        self.send_command(f'tellraw @a {json.dumps(tellraw_json)}')
        print(f"[RESPONSE] Sent rules to {username}")

    # Admin Commands

    def cmd_adminhelp(self, username, args):
        """Admin help command - shows admin commands"""
        if not self.is_admin(username):
            self.send_command(f"tell {username} You don't have permission to use this command!")
            return

        tellraw_json = {
            "text": "",
            "extra": [
                {"text": f"[ADMIN {username}] ", "color": "red"},
                {"text": "Admin commands: ", "color": "white"},
                {"text": "!unban <player>", "color": "gold"},
                {"text": ", ", "color": "white"},
                {"text": "!addtime <player> <hours>", "color": "gold"},
                {"text": ", ", "color": "white"},
                {"text": "!resettime <player>", "color": "gold"}
            ]
        }
        self.send_command(f'tellraw {username} {json.dumps(tellraw_json)}')
        print(f"[ADMIN] {username} requested admin help")

    def cmd_unban(self, username, args):
        """Unban command - removes a player from the ban list"""
        if not self.is_admin(username):
            self.send_command(f"tell {username} You don't have permission to use this command!")
            return

        if not args:
            self.send_command(f"tell {username} Usage: !unban <player>")
            return

        target_player = args[0]

        # Load sessions and unban the player
        session_manager.load_sessions()
        if target_player in session_manager.sessions:
            session_manager.sessions[target_player]["banned"] = False
            session_manager.save_sessions()

            # Execute minecraft unban command
            self.send_command(f"pardon {target_player}")

            # Announce the unban
            tellraw_json = {
                "text": "",
                "extra": [
                    {"text": f"[ADMIN {username}] ", "color": "red"},
                    {"text": f"Unbanned ", "color": "white"},
                    {"text": target_player, "color": "yellow", "bold": True}
                ]
            }
            self.send_command(f'tellraw @a {json.dumps(tellraw_json)}')
            print(f"[ADMIN] {username} unbanned {target_player}")
        else:
            self.send_command(f"tell {username} Player {target_player} not found in session data")

    def cmd_addtime(self, username, args):
        """Add time command - adds hours to a player's rollover time"""
        if not self.is_admin(username):
            self.send_command(f"tell {username} You don't have permission to use this command!")
            return

        if len(args) < 2:
            self.send_command(f"tell {username} Usage: !addtime <player> <hours>")
            return

        target_player = args[0]
        try:
            hours_to_add = float(args[1])
        except ValueError:
            self.send_command(f"tell {username} Invalid hours value. Must be a number.")
            return

        # Load sessions and add time
        session_manager.load_sessions()
        if target_player in session_manager.sessions:
            current_rollover = session_manager.sessions[target_player].get("rollover_time", 0)
            session_manager.sessions[target_player]["rollover_time"] = current_rollover + (hours_to_add * 3600)
            session_manager.save_sessions()

            # Announce the time addition
            tellraw_json = {
                "text": "",
                "extra": [
                    {"text": f"[ADMIN {username}] ", "color": "red"},
                    {"text": f"Added ", "color": "white"},
                    {"text": f"{hours_to_add} hours", "color": "green", "bold": True},
                    {"text": f" to ", "color": "white"},
                    {"text": target_player, "color": "yellow", "bold": True}
                ]
            }
            self.send_command(f'tellraw @a {json.dumps(tellraw_json)}')

            # Notify the target player if they're online
            if session_manager.sessions[target_player].get("online", False):
                self.send_command(f"tell {target_player} An admin has granted you {hours_to_add} extra hours!")

            print(f"[ADMIN] {username} added {hours_to_add} hours to {target_player}")
        else:
            self.send_command(f"tell {username} Player {target_player} not found in session data")


    def cmd_resettime(self, username, args):
        """Reset time command - resets a player's session completely"""
        if not self.is_admin(username):
            self.send_command(f"tell {username} You don't have permission to use this command!")
            return

        if not args:
            self.send_command(f"tell {username} Usage: !resettime <player>")
            return

        target_player = args[0]

        # Load sessions and reset the player
        session_manager.load_sessions()
        if target_player in session_manager.sessions:
            session_manager.sessions[target_player]["playtime"] = 0
            session_manager.sessions[target_player]["rollover_time"] = 0
            session_manager.sessions[target_player]["banned"] = False
            # Reset announcements
            for k in session_manager.sessions[target_player]["announcements"]:
                session_manager.sessions[target_player]["announcements"][k] = False
            session_manager.save_sessions()

            # Unban if needed
            self.send_command(f"pardon {target_player}")

            # Announce the reset
            tellraw_json = {
                "text": "",
                "extra": [
                    {"text": f"[ADMIN {username}] ", "color": "red"},
                    {"text": f"Reset ", "color": "white"},
                    {"text": target_player, "color": "yellow", "bold": True},
                    {"text": "'s session (full 3 hours restored)", "color": "green"}
                ]
            }
            self.send_command(f'tellraw @a {json.dumps(tellraw_json)}')

            # Notify the target player if they're online
            if session_manager.sessions[target_player].get("online", False):
                self.send_command(f"tell {target_player} An admin has reset your session! You now have full playtime available.")

            print(f"[ADMIN] {username} reset {target_player}'s session")
        else:
            self.send_command(f"tell {username} Player {target_player} not found in session data")
