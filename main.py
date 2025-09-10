from exaroton import Exaroton
from dotenv import load_dotenv
import os
import threading
import time

import session_manager

load_dotenv()

exa = Exaroton(os.environ.get("API_KEY"))
SERVER_NAME = os.environ.get("SERVER_NAME")


def get_server_id(server_name: str) -> str:
    servers = exa.get_servers()
    for server in servers:
        if server.name == server_name:
            return server.id
    return ""


def get_server_online_players(server_name: str) -> list:
    servers = exa.get_servers()
    for server in servers:
        if server.name == server_name:
            return server.players.list
    return []


def server_is_online(server_name: str) -> bool:
    servers = exa.get_servers()
    for server in servers:
        if server.name == server_name:
            return server.status == "Online"
    return False


def send_tell(server_name: str, player: str, message: str):
    try:
        server_id = get_server_id(server_name)
        if not server_id:
            print(f"Server '{server_name}' not found!")
            return
        if player:
            command = f"tell {player} {message}"
        else:
            command = f"say {message}"
        exa.command(server_id, command)
        print(f"Sent to {player or 'ALL'}: {message}")
    except Exception as e:
        print(f"Failed to send message to {player or 'ALL'}: {e}")


def run_command(server_name: str, command: str):
    """Execute an arbitrary server command."""
    try:
        server_id = get_server_id(server_name)
        if not server_id:
            print(f"Server '{server_name}' not found!")
            return
        exa.command(server_id, command)
        print(f"Executed command: {command}")
    except Exception as e:
        print(f"Failed to execute command '{command}': {e}")


def managed_session_manager(server_name):
    """
    Wrapper that only runs session manager when the server is online.
    If server is offline → pause tracking until it comes back.
    """
    last_state = 0 # 0 = offline, 1 = online
    while True:
        if server_is_online(server_name):
            last_state = 1
            print(f"[INFO] Server '{server_name}' is online. Session manager active.")
            send_tell(server_name, None, "ATTR is now watching this server. GLHF (in moderation)")
            try:
                while server_is_online(server_name):
                    session_manager.session_cycle(
                        get_online_players=lambda: get_server_online_players(server_name),
                        send_message=lambda player, msg: send_tell(server_name, player, msg),
                        run_command=lambda cmd: run_command(server_name, cmd)
                    )
            except Exception as e:
                print(f"[ERROR] Session manager crashed: {e}")
        else:
            if last_state == 1:
                print(f"[INFO] Server '{server_name}' is offline. Pausing session tracking.")
            last_state = 0
        time.sleep(60)  # check every 60s if server status changed


if __name__ == "__main__":
    server_id = get_server_id(SERVER_NAME)
    if not server_id:
        print(f"Server '{SERVER_NAME}' not found!")
        exit(1)

    print(f"Monitoring server '{SERVER_NAME}' with ID {server_id}")

    threading.Thread(
        target=managed_session_manager,
        args=(SERVER_NAME,),
        daemon=True
    ).start()

    while True:  # placeholder for extra tasks
        time.sleep(10)
