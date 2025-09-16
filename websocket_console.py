import websocket
import json
import time
import os
from dotenv import load_dotenv
from command_handler import CommandHandler

load_dotenv()
DEBUG_MODE = False
SEND_READY_MESSAGE = True  # Set to False to disable ready message

class WebSocketConsoleMonitor:
    """Simple WebSocket monitor to print server console to stdout"""

    def __init__(self, api_token, server_id):
        self.api_token = api_token
        self.server_id = server_id
        self.ws = None
        self.running = False
        self.ready = False
        self.console_subscribed = False
        self.needs_reconnect = False

        # Initialize command handler
        self.command_handler = None

    def on_message(self, ws, message):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            stream = data.get("stream")
            msg_data = data.get("data")

            # Handle non-stream messages
            if not stream:
                if msg_type == "ready":
                    print(f"[WS] Ready - Server ID: {msg_data}")
                    self.ready = True
                    # Subscribe to console stream
                    self.subscribe_to_console()

                elif msg_type == "connected":
                    print("[WS] Connected to game server")

                elif msg_type == "disconnected":
                    reason = msg_data
                    print(f"[WS] Disconnected from game server: {reason}")
                    self.console_subscribed = False

                    # Handle different disconnection reasons
                    if reason == "server-stop":
                        print("[WS] Server stopped - will wait for server to come back online")
                        self.needs_reconnect = True
                    elif reason == "invalid-status":
                        print("[WS] Server not in valid state for console connection")
                        self.needs_reconnect = True
                    elif reason == "server-transfer":
                        print("[WS] Server is being transferred - will reconnect when ready")
                        self.needs_reconnect = True
                    else:
                        print(f"[WS] Unexpected disconnection reason: {reason}")
                        self.needs_reconnect = True

                    print("[WS] Triggering reconnection...")
                    # Close the WebSocket to trigger reconnection
                    if self.ws:
                        self.ws.close()

                elif msg_type == "keep-alive":
                    # Ignore keep-alive messages
                    pass

            # Handle stream messages
            else:
                if stream == "status" and msg_type == "status":
                    if msg_data:
                        status_code = msg_data.get("status", 0)
                        status_names = {
                            0: "OFFLINE", 1: "ONLINE", 2: "STARTING", 3: "STOPPING",
                            4: "RESTARTING", 5: "SAVING", 6: "LOADING", 7: "CRASHED",
                            8: "PENDING", 9: "TRANSFERRING", 10: "PREPARING"
                        }
                        status_name = status_names.get(status_code, "UNKNOWN")
                        print(f"[WS] Server status: {status_name}")

                elif stream == "console":
                    if msg_type == "started":
                        print("[WS] Console stream started")
                        self.console_subscribed = True
                        # Send ready message to chat
                        self.send_ready_message()

                    elif msg_type == "line" and msg_data:
                        if DEBUG_MODE:
                            # Print console line to stdout
                            print(f"[CONSOLE] {msg_data}")

                        # Process line through command handler
                        if self.command_handler:
                            self.command_handler.process_console_line(msg_data)

        except json.JSONDecodeError as e:
            print(f"[WS ERROR] Failed to parse message: {e}")
        except Exception as e:
            print(f"[WS ERROR] Error handling message: {e}")

    def on_error(self, ws, error):
        """Handle WebSocket errors"""
        print(f"[WS ERROR] {error}")

    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close"""
        if self.needs_reconnect:
            print("[WS] Connection closed for reconnection")
            self.needs_reconnect = False
        else:
            print(f"[WS] Connection closed - Code: {close_status_code}, Message: {close_msg}")
        self.ready = False
        self.console_subscribed = False
        self.running = False

    def on_open(self, ws):
        """Handle WebSocket open"""
        print("[WS] Connection opened")

    def subscribe_to_console(self):
        """Subscribe to console stream"""
        if self.ready and self.ws:
            message = {
                "stream": "console",
                "type": "start",
                "data": {"tail": 50}  # Get last 50 lines
            }
            self.ws.send(json.dumps(message))
            print("[WS] Subscribing to console stream...")

    def send_command(self, command):
        """Send a command to the server via console stream"""
        if self.console_subscribed and self.ws:
            message = {
                "stream": "console",
                "type": "command",
                "data": command
            }
            self.ws.send(json.dumps(message))
            print(f"[WS] Sent command: {command}")

    def send_ready_message(self):
        """Send a ready for commands message to chat"""
        if not SEND_READY_MESSAGE:
            print("[WS] Ready message disabled, skipping...")
            return

        try:
            # Use tellraw for better formatting
            tellraw_message = {
                "text": "",
                "extra": [
                    {"text": "[", "color": "gray"},
                    {"text": "ATTR", "color": "green", "bold": True},
                    {"text": "] ", "color": "gray"},
                    {"text": "Ready for commands! ", "color": "aqua"},
                    {"text": "Type ", "color": "white"},
                    {"text": "!help", "color": "yellow", "bold": True},
                    {"text": " for available commands.", "color": "white"}
                ]
            }
            ready_command = f"tellraw @a {json.dumps(tellraw_message)}"
            self.send_command(ready_command)
            print("[WS] Sent ready for commands message to chat")
        except Exception as e:
            print(f"[WS ERROR] Failed to send ready message: {e}")
            # Fallback to simple say command
            try:
                fallback_command = "say [ATTR] Ready for commands! Type !help for available commands."
                self.send_command(fallback_command)
                print("[WS] Sent fallback ready message to chat")
            except Exception as e2:
                print(f"[WS ERROR] Failed to send fallback ready message: {e2}")

    def connect(self):
        """Connect to WebSocket"""
        url = f"wss://api.exaroton.com/v1/servers/{self.server_id}/websocket"
        headers = {
            "Authorization": f"Bearer {self.api_token}"
        }

        print(f"[WS] Connecting to {url}")

        # Initialize command handler with send_command function
        self.command_handler = CommandHandler(self.send_command)

        self.ws = websocket.WebSocketApp(
            url,
            header=headers,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )

        self.running = True
        # This will block until connection closes
        self.ws.run_forever()

    def disconnect(self):
        """Disconnect from WebSocket"""
        if self.ws:
            self.running = False
            self.ws.close()
            print("[WS] Disconnecting...")


def run_websocket_monitor(api_token, server_id):
    """Thread function to run WebSocket monitor with exponential backoff"""
    monitor = WebSocketConsoleMonitor(api_token, server_id)

    base_delay = 5
    max_delay = 300  # Maximum 5 minutes
    current_delay = base_delay
    attempt = 0
    consecutive_failures = 0

    while True:
        try:
            if attempt == 0:
                print("[WS] Starting WebSocket monitor...")
            else:
                print(f"[WS] Starting WebSocket monitor (reconnection attempt #{attempt})...")

            # Track connection start time
            connection_start = time.time()
            monitor.connect()
            connection_duration = time.time() - connection_start

            # If we were connected for more than 30 seconds, reset failure counters
            if connection_duration > 30:
                attempt = 0
                consecutive_failures = 0
                current_delay = base_delay
                print("[WS] Connection was stable, reset reconnection counters")

            # Connection ended, check if we need to reconnect
            if monitor.needs_reconnect:
                # Server-initiated disconnection, use shorter delay
                current_delay = base_delay
                print(f"[WS] Server-initiated disconnect, reconnecting in {current_delay} seconds...")
            else:
                # Unexpected disconnection, use exponential backoff
                attempt += 1
                consecutive_failures += 1
                current_delay = min(base_delay * (2 ** min(attempt, 10)), max_delay)
                print(f"[WS] Unexpected disconnect, reconnecting in {current_delay} seconds...")

                # If too many consecutive failures, add extra delay
                if consecutive_failures > 5:
                    print(f"[WS] Too many failures ({consecutive_failures}), adding extra delay...")
                    current_delay = max_delay

            time.sleep(current_delay)

        except KeyboardInterrupt:
            print("[WS] Stopping WebSocket monitor...")
            break
        except Exception as e:
            print(f"[WS ERROR] Monitor error: {e}")
            attempt += 1
            current_delay = min(base_delay * (2 ** attempt), max_delay)
            print(f"[WS] Retrying connection in {current_delay} seconds (attempt #{attempt})...")
            time.sleep(current_delay)


if __name__ == "__main__":
    # Test standalone
    API_TOKEN = os.environ.get("API_KEY")
    SERVER_ID = os.environ.get("SERVER_ID")  # You'll need to add this to .env or get it from main.py

    if not API_TOKEN:
        print("Error: API_KEY not found in environment variables")
        exit(1)

    if not SERVER_ID:
        print("Error: SERVER_ID not found in environment variables")
        print("You can get the server ID from main.py or add it to your .env file")
        exit(1)

    # Run in main thread for testing
    run_websocket_monitor(API_TOKEN, SERVER_ID)
