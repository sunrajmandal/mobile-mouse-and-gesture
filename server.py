"""
NeoPointer — Bluetooth & WebSocket Remote Control Server
=========================================================
Dual-mode PC receiver: Native Bluetooth RFCOMM + FastAPI WebSocket.
Turns a mobile phone into a wireless mouse, keyboard, and command console.
"""

import asyncio
import ctypes
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pyautogui
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False
SCREEN_W, SCREEN_H = pyautogui.size()

BT_RFCOMM_CHANNEL = 7  # Found to be available during research
WS_PORT = 8765

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [NeoPointer] %(message)s",
)
logger = logging.getLogger("neopointer")

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(title="NeoPointer Bluetooth Control Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# ---------------------------------------------------------------------------
# Shared State
# ---------------------------------------------------------------------------
class NeoState:
    def __init__(self):
        self.control_enabled: bool = True
        self.precision_mode: bool = False
        self.drag_mode: bool = False
        self.cursor_sensitivity: float = 2.5
        self.scroll_sensitivity: float = 5.0
        self.bt_connected: bool = False
        self.ws_connected: bool = False
        self.last_activity: float = time.time()
        self.command_history: list = []
        self.latency_ms: float = 0.0
        self.lock = threading.Lock()

    def activity(self):
        self.last_activity = time.time()

state = NeoState()
ws_clients: list[WebSocket] = []

# ---------------------------------------------------------------------------
# Unified Command Parser
# ---------------------------------------------------------------------------
def parse_and_execute(raw: str):
    """Parse raw string or JSON commands and execute OS actions."""
    raw = raw.strip()
    if not raw or not state.control_enabled:
        return

    state.activity()

    # Store in history
    with state.lock:
        state.command_history.append({"cmd": raw, "ts": time.time()})
        if len(state.command_history) > 50:
            state.command_history.pop(0)

    # --- Try JSON format first ---
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            action = data.get("action", "").lower()
            if action == "move":
                _do_move(data.get("dx", 0), data.get("dy", 0))
            elif action == "click":
                _do_click(data.get("button", "left"), data.get("double", False))
            elif action == "scroll":
                _do_scroll(data.get("dy", 0))
            elif action == "drag_start":
                _do_drag_start()
            elif action == "drag_end":
                _do_drag_end()
            elif action == "type":
                _do_type(data.get("text", ""))
            elif action == "key":
                _do_key(data.get("key", ""))
            elif action == "hotkey":
                _do_hotkey(data.get("keys", []))
            return
        except json.JSONDecodeError:
            pass

    # --- Try structured format (MOVE:dx,dy / CLICK / etc.) ---
    upper = raw.upper()
    if upper.startswith("MOVE:"):
        parts = raw[5:].split(",")
        if len(parts) == 2:
            try:
                _do_move(float(parts[0]), float(parts[1]))
            except ValueError:
                pass
        return
    if upper == "CLICK":
        _do_click("left")
        return
    if upper == "DOUBLE_CLICK":
        _do_click("left", double=True)
        return
    if upper == "RIGHT_CLICK":
        _do_click("right")
        return
    if upper.startswith("SCROLL:"):
        try:
            _do_scroll(float(raw[7:]))
        except ValueError:
            pass
        return
    if upper.startswith("TYPE:"):
        _do_type(raw[5:])
        return
    if upper == "DRAG_START":
        _do_drag_start()
        return
    if upper == "DRAG_END":
        _do_drag_end()
        return

    # --- Natural language command console ---
    _parse_console_command(raw.lower())


def _parse_console_command(cmd: str):
    """Parse human-readable console commands."""
    # Click commands
    if cmd in ("click", "left click", "tap"):
        _do_click("left")
    elif cmd in ("right click", "right-click", "rclick"):
        _do_click("right")
    elif cmd in ("double click", "double-click", "dclick"):
        _do_click("left", double=True)
    elif cmd in ("middle click", "middle-click"):
        _do_click("middle")

    # Movement commands
    elif cmd.startswith("move left"):
        px = _extract_number(cmd, 50)
        _do_move(-px, 0)
    elif cmd.startswith("move right"):
        px = _extract_number(cmd, 50)
        _do_move(px, 0)
    elif cmd.startswith("move up"):
        px = _extract_number(cmd, 50)
        _do_move(0, -px)
    elif cmd.startswith("move down"):
        px = _extract_number(cmd, 50)
        _do_move(0, px)

    # Scroll commands
    elif cmd in ("scroll up", "scroll-up"):
        _do_scroll(5)
    elif cmd in ("scroll down", "scroll-down"):
        _do_scroll(-5)

    # Keyboard shortcuts
    elif cmd == "copy":
        _do_hotkey(["ctrl", "c"])
    elif cmd == "paste":
        _do_hotkey(["ctrl", "v"])
    elif cmd == "cut":
        _do_hotkey(["ctrl", "x"])
    elif cmd == "undo":
        _do_hotkey(["ctrl", "z"])
    elif cmd == "redo":
        _do_hotkey(["ctrl", "y"])
    elif cmd == "select all":
        _do_hotkey(["ctrl", "a"])
    elif cmd == "save":
        _do_hotkey(["ctrl", "s"])
    elif cmd in ("switch desktop", "switch window", "alt tab"):
        _do_hotkey(["alt", "tab"])
    elif cmd in ("show desktop", "minimize all", "win d"):
        _do_hotkey(["win", "d"])
    elif cmd in ("task manager", "taskmgr"):
        _do_hotkey(["ctrl", "shift", "esc"])
    elif cmd == "close":
        _do_hotkey(["alt", "f4"])
    elif cmd == "new tab":
        _do_hotkey(["ctrl", "t"])
    elif cmd == "close tab":
        _do_hotkey(["ctrl", "w"])
    elif cmd == "refresh":
        _do_key("f5")
    elif cmd == "fullscreen":
        _do_key("f11")
    elif cmd == "screenshot":
        _do_hotkey(["win", "shift", "s"])
    elif cmd == "lock":
        _do_hotkey(["win", "l"])
    elif cmd == "search":
        _do_hotkey(["win", "s"])
    elif cmd == "enter":
        _do_key("enter")
    elif cmd == "escape" or cmd == "esc":
        _do_key("escape")
    elif cmd == "backspace":
        _do_key("backspace")
    elif cmd == "delete":
        _do_key("delete")
    elif cmd == "tab":
        _do_key("tab")
    elif cmd == "space":
        _do_key("space")

    # Open applications
    elif cmd.startswith("open "):
        app_name = cmd[5:].strip()
        _open_app(app_name)

    # Type text
    elif cmd.startswith("type "):
        text = cmd[5:]
        _do_type(text)

    # Key press
    elif cmd.startswith("press "):
        key = cmd[6:].strip()
        _do_key(key)

    else:
        logger.info(f"Unknown command: {cmd}")


def _extract_number(cmd: str, default: int) -> int:
    """Extract a trailing number from a command string."""
    parts = cmd.split()
    if len(parts) >= 3:
        try:
            return int(parts[-1])
        except ValueError:
            pass
    return default


# ---------------------------------------------------------------------------
# OS Control Functions
# ---------------------------------------------------------------------------
def _do_move(dx: float, dy: float):
    sens = state.cursor_sensitivity * (0.4 if state.precision_mode else 1.0)
    cur_x, cur_y = pyautogui.position()
    nx = max(0, min(SCREEN_W - 1, cur_x + dx * sens))
    ny = max(0, min(SCREEN_H - 1, cur_y + dy * sens))
    ctypes.windll.user32.SetCursorPos(int(nx), int(ny))


def _do_click(button: str = "left", double: bool = False):
    if double:
        pyautogui.doubleClick(button=button, _pause=False)
    else:
        pyautogui.click(button=button, _pause=False)


def _do_scroll(dy: float):
    pyautogui.scroll(int(dy * state.scroll_sensitivity), _pause=False)


def _do_drag_start():
    pyautogui.mouseDown(_pause=False)
    state.drag_mode = True


def _do_drag_end():
    pyautogui.mouseUp(_pause=False)
    state.drag_mode = False


def _do_type(text: str):
    pyautogui.write(text, interval=0.01, _pause=False)


def _do_key(key: str):
    try:
        pyautogui.press(key, _pause=False)
    except Exception as e:
        logger.warning(f"Key press failed for '{key}': {e}")


def _do_hotkey(keys: list):
    try:
        pyautogui.hotkey(*keys, _pause=False)
    except Exception as e:
        logger.warning(f"Hotkey failed for {keys}: {e}")


def _open_app(name: str):
    """Open an application by name using Windows search."""
    try:
        # Try direct execution first
        common_apps = {
            "chrome": "chrome",
            "firefox": "firefox",
            "edge": "msedge",
            "notepad": "notepad",
            "calculator": "calc",
            "explorer": "explorer",
            "cmd": "cmd",
            "powershell": "powershell",
            "paint": "mspaint",
            "word": "winword",
            "excel": "excel",
            "spotify": "spotify",
        }
        exe = common_apps.get(name.lower())
        if exe:
            subprocess.Popen(exe, shell=True)
        else:
            # Use Windows Run dialog
            pyautogui.hotkey("win", "r", _pause=False)
            time.sleep(0.3)
            pyautogui.write(name, interval=0.02, _pause=False)
            time.sleep(0.1)
            pyautogui.press("enter", _pause=False)
        logger.info(f"Opened: {name}")
    except Exception as e:
        logger.warning(f"Failed to open '{name}': {e}")


# ---------------------------------------------------------------------------
# Status Broadcast
# ---------------------------------------------------------------------------
async def broadcast_status():
    msg = json.dumps({
        "type": "status",
        "control_enabled": state.control_enabled,
        "precision_mode": state.precision_mode,
        "drag_mode": state.drag_mode,
        "bt_connected": state.bt_connected,
        "ws_connected": len(ws_clients) > 0,
        "sensitivity": state.cursor_sensitivity,
        "scroll_sensitivity": state.scroll_sensitivity,
        "latency_ms": state.latency_ms,
    })
    for ws in list(ws_clients):
        try:
            await ws.send_text(msg)
        except:
            pass


# ---------------------------------------------------------------------------
# WebSocket Handler
# ---------------------------------------------------------------------------
@app.get("/")
async def serve_frontend():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.websocket("/ws")
async def ws_handler(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    state.ws_connected = True
    logger.info("📱 Mobile WebSocket connected")
    await broadcast_status()

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type", "")

            if msg_type == "move" and state.control_enabled:
                _do_move(data.get("dx", 0), data.get("dy", 0))
            elif msg_type == "click" and state.control_enabled:
                _do_click(data.get("button", "left"), data.get("double", False))
            elif msg_type == "scroll" and state.control_enabled:
                _do_scroll(data.get("dy", 0))
            elif msg_type == "drag_start" and state.control_enabled:
                _do_drag_start()
            elif msg_type == "drag_end" and state.control_enabled:
                _do_drag_end()
            elif msg_type == "drag_toggle" and state.control_enabled:
                if state.drag_mode:
                    _do_drag_end()
                else:
                    _do_drag_start()
            elif msg_type == "type_text" and state.control_enabled:
                _do_type(data.get("text", ""))
            elif msg_type == "key_press" and state.control_enabled:
                _do_key(data.get("key", ""))
            elif msg_type == "hotkey" and state.control_enabled:
                _do_hotkey(data.get("keys", []))
            elif msg_type == "console_command" and state.control_enabled:
                parse_and_execute(data.get("command", ""))
            elif msg_type == "set_sensitivity":
                state.cursor_sensitivity = data.get("value", 2.5)
            elif msg_type == "set_scroll_sensitivity":
                state.scroll_sensitivity = data.get("value", 5.0)
            elif msg_type == "set_precision":
                state.precision_mode = data.get("value", False)
            elif msg_type == "pause_resume":
                state.control_enabled = not state.control_enabled
            elif msg_type == "ping":
                await ws.send_text(json.dumps({"type": "pong", "ts": data.get("ts", 0)}))
                continue

            state.activity()
            await broadcast_status()

    except WebSocketDisconnect:
        ws_clients.remove(ws)
        state.ws_connected = len(ws_clients) > 0
        logger.info("📱 Mobile WebSocket disconnected")
        await broadcast_status()


# ---------------------------------------------------------------------------
# Bluetooth RFCOMM Server (Background Thread)
# ---------------------------------------------------------------------------
def bt_rfcomm_server():
    """Native Bluetooth RFCOMM socket server using Python's built-in socket."""
    while True:
        try:
            sock = socket.socket(
                socket.AF_BLUETOOTH,
                socket.SOCK_STREAM,
                socket.BTPROTO_RFCOMM,
            )
            sock.bind((socket.BDADDR_ANY, BT_RFCOMM_CHANNEL))
            sock.listen(1)
            logger.info(f"🔵 Bluetooth RFCOMM listening on channel {BT_RFCOMM_CHANNEL}")
            state.bt_connected = False

            while True:
                client, addr = sock.accept()
                state.bt_connected = True
                logger.info(f"🔵 Bluetooth device connected: {addr}")

                buffer = ""
                try:
                    while True:
                        chunk = client.recv(1024).decode("utf-8", errors="ignore")
                        if not chunk:
                            break
                        buffer += chunk
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if line:
                                parse_and_execute(line)
                except (ConnectionResetError, OSError) as e:
                    logger.info(f"🔵 Bluetooth device disconnected: {e}")
                finally:
                    state.bt_connected = False
                    client.close()

        except PermissionError:
            logger.warning("🔵 Bluetooth RFCOMM channel blocked. Trying next channel...")
            # Try next available channel
            for ch in range(BT_RFCOMM_CHANNEL + 1, 31):
                try:
                    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                    sock.bind((socket.BDADDR_ANY, ch))
                    sock.listen(1)
                    logger.info(f"🔵 Bluetooth RFCOMM bound to fallback channel {ch}")
                    break
                except:
                    continue
            else:
                logger.error("🔵 No available RFCOMM channels. Retrying in 10s...")
                time.sleep(10)
                continue

        except OSError as e:
            logger.warning(f"🔵 Bluetooth error: {e}. Retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"🔵 Bluetooth fatal error: {e}. Retrying in 10s...")
            time.sleep(10)


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def main():
    import uvicorn

    # Start Bluetooth RFCOMM server in background thread
    bt_thread = threading.Thread(target=bt_rfcomm_server, daemon=True)
    bt_thread.start()

    logger.info("🚀 NeoPointer AI Bluetooth Control Server Online")
    logger.info(f"📡 WebSocket server: http://0.0.0.0:{WS_PORT}")
    logger.info(f"🔵 Bluetooth RFCOMM: Channel {BT_RFCOMM_CHANNEL}")

    uvicorn.run(app, host="0.0.0.0", port=WS_PORT, log_level="error")


if __name__ == "__main__":
    main()
