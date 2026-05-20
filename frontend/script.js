/**
 * NeoPointer — Advanced Touch Engine & WebSocket Client
 * =====================================================
 * High-performance multi-touch gesture recognition with
 * auto-reconnect, latency monitoring, and haptic feedback.
 */

// ---------------------------------------------------------------------------
// WebSocket Connection
// ---------------------------------------------------------------------------
let ws = null;
let reconnectTimer = null;
const WS_URL = `ws://${location.host}/ws`;

function connect() {
    if (ws && ws.readyState === WebSocket.OPEN) return;

    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        document.getElementById("ws-dot").classList.add("online");
        clearTimeout(reconnectTimer);
        startLatencyPing();
    };

    ws.onclose = () => {
        document.getElementById("ws-dot").classList.remove("online");
        reconnectTimer = setTimeout(connect, 2000);
    };

    ws.onerror = () => {
        ws.close();
    };

    ws.onmessage = (evt) => {
        try {
            const data = JSON.parse(evt.data);
            if (data.type === "status") handleStatus(data);
            if (data.type === "pong") handlePong(data);
        } catch (e) {}
    };
}

function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(obj));
    }
}

// ---------------------------------------------------------------------------
// Latency Monitor
// ---------------------------------------------------------------------------
let pingInterval = null;

function startLatencyPing() {
    clearInterval(pingInterval);
    pingInterval = setInterval(() => {
        send({ type: "ping", ts: Date.now() });
    }, 3000);
}

function handlePong(data) {
    const latency = Date.now() - data.ts;
    document.getElementById("latency-display").textContent = `${latency}ms`;
}

// ---------------------------------------------------------------------------
// Status Handler
// ---------------------------------------------------------------------------
function handleStatus(data) {
    // Bluetooth dot
    const btDot = document.getElementById("bt-dot");
    btDot.classList.toggle("online", !!data.bt_connected);

    // Precision badge
    const badge = document.getElementById("precision-badge");
    badge.classList.toggle("visible", !!data.precision_mode);

    // Drag button
    const dragBtn = document.getElementById("btn-drag");
    dragBtn.classList.toggle("drag-active", !!data.drag_mode);
    dragBtn.querySelector("span").textContent = data.drag_mode ? "Release" : "Drag";

    // Precision toggle
    const precBtn = document.getElementById("btn-precision");
    precBtn.classList.toggle("active", !!data.precision_mode);
    precBtn.textContent = data.precision_mode ? "ON" : "OFF";

    // Kill switch
    const killBtn = document.getElementById("btn-kill");
    killBtn.textContent = data.control_enabled ? "LOCK SYSTEM" : "UNLOCK SYSTEM";
    killBtn.classList.toggle("danger-outline", data.control_enabled);
    if (!data.control_enabled) {
        killBtn.style.background = "var(--success)";
        killBtn.style.color = "#000";
        killBtn.style.borderColor = "transparent";
    } else {
        killBtn.style.background = "";
        killBtn.style.color = "";
        killBtn.style.borderColor = "";
    }
}

// ---------------------------------------------------------------------------
// Touch Settings
// ---------------------------------------------------------------------------
let cursorSensitivity = 2.5;
let scrollSensitivity = 5.0;

// ---------------------------------------------------------------------------
// Advanced Touch Engine
// ---------------------------------------------------------------------------
const touchpad = document.getElementById("touchpad");
const indicator = document.getElementById("touch-indicator");

// Touch State Machine
let touchStartTime = 0;
let lastTapTime = 0;
let tapCount = 0;
let isLongPress = false;
let longPressTimer = null;
let isDragging = false;
let lastX = 0, lastY = 0;
let touchFingers = 0;
let scrollStartY = 0;
let hasMoved = false;
const MOVE_THRESHOLD = 5;
const LONG_PRESS_MS = 400;
const DOUBLE_TAP_MS = 300;

touchpad.addEventListener("touchstart", (e) => {
    e.preventDefault();
    touchFingers = e.touches.length;
    const t = e.touches[0];
    lastX = t.clientX;
    lastY = t.clientY;
    touchStartTime = Date.now();
    hasMoved = false;

    // Show indicator
    indicator.style.left = t.clientX - touchpad.getBoundingClientRect().left + "px";
    indicator.style.top = t.clientY - touchpad.getBoundingClientRect().top + "px";
    indicator.classList.add("visible");
    touchpad.classList.add("active");

    // Long press detection
    clearTimeout(longPressTimer);
    if (touchFingers === 1) {
        longPressTimer = setTimeout(() => {
            if (!hasMoved) {
                isLongPress = true;
                isDragging = true;
                send({ type: "drag_start" });
                vibrate(50);
            }
        }, LONG_PRESS_MS);
    }

    // Two-finger scroll start
    if (touchFingers === 2) {
        scrollStartY = t.clientY;
        clearTimeout(longPressTimer);
    }
}, { passive: false });

touchpad.addEventListener("touchmove", (e) => {
    e.preventDefault();
    const t = e.touches[0];
    const dx = t.clientX - lastX;
    const dy = t.clientY - lastY;

    if (Math.abs(dx) > MOVE_THRESHOLD || Math.abs(dy) > MOVE_THRESHOLD) {
        hasMoved = true;
    }

    // Update indicator
    indicator.style.left = t.clientX - touchpad.getBoundingClientRect().left + "px";
    indicator.style.top = t.clientY - touchpad.getBoundingClientRect().top + "px";

    if (touchFingers === 1) {
        // Single finger = mouse movement
        send({ type: "move", dx, dy });
        lastX = t.clientX;
        lastY = t.clientY;
    } else if (touchFingers >= 2 && e.touches.length >= 2) {
        // Two fingers = scroll
        const scrollDy = t.clientY - lastY;
        if (Math.abs(scrollDy) > 2) {
            send({ type: "scroll", dy: scrollDy > 0 ? -1 : 1 });
        }
        lastX = t.clientX;
        lastY = t.clientY;
    }
}, { passive: false });

touchpad.addEventListener("touchend", (e) => {
    e.preventDefault();
    indicator.classList.remove("visible");
    touchpad.classList.remove("active");
    clearTimeout(longPressTimer);

    const elapsed = Date.now() - touchStartTime;

    // End drag if active
    if (isDragging) {
        send({ type: "drag_end" });
        isDragging = false;
        isLongPress = false;
        vibrate(20);
        return;
    }

    // Gesture recognition (only if no significant movement)
    if (!hasMoved && elapsed < 300) {
        if (touchFingers === 2) {
            // Two-finger tap = right click
            send({ type: "click", button: "right" });
            vibrate(30);
        } else if (touchFingers === 1) {
            // Single finger tap
            const now = Date.now();
            if (now - lastTapTime < DOUBLE_TAP_MS) {
                // Double tap
                tapCount++;
                if (tapCount >= 2) {
                    send({ type: "click", button: "left", double: true });
                    vibrate(40);
                    tapCount = 0;
                }
            } else {
                tapCount = 1;
                // Delay single tap to check for double
                setTimeout(() => {
                    if (tapCount === 1) {
                        send({ type: "click", button: "left" });
                        vibrate(15);
                    }
                    tapCount = 0;
                }, DOUBLE_TAP_MS);
            }
            lastTapTime = now;
        }
    }

    touchFingers = 0;
}, { passive: false });

// ---------------------------------------------------------------------------
// Button Controls
// ---------------------------------------------------------------------------
document.getElementById("btn-left-click").addEventListener("click", () => {
    send({ type: "click", button: "left" });
    vibrate(15);
});

document.getElementById("btn-right-click").addEventListener("click", () => {
    send({ type: "click", button: "right" });
    vibrate(20);
});

document.getElementById("btn-drag").addEventListener("click", () => {
    send({ type: "drag_toggle" });
    vibrate(30);
});

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
document.querySelectorAll(".nav-item").forEach(btn => {
    btn.addEventListener("click", () => {
        const target = btn.dataset.layer;

        document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");

        document.querySelectorAll(".app-layer").forEach(l => l.classList.remove("active"));
        document.getElementById(target).classList.add("active");

        vibrate(10);
    });
});

// ---------------------------------------------------------------------------
// Console
// ---------------------------------------------------------------------------
const consoleInput = document.getElementById("console-input");
const consoleOutput = document.getElementById("console-output");

function addConsoleLine(text, cls = "") {
    const line = document.createElement("div");
    line.className = "console-line " + cls;
    line.textContent = text;
    consoleOutput.appendChild(line);
    consoleOutput.scrollTop = consoleOutput.scrollHeight;
}

function executeConsoleCommand() {
    const cmd = consoleInput.value.trim();
    if (!cmd) return;

    addConsoleLine(cmd, "user");
    send({ type: "console_command", command: cmd });
    addConsoleLine(`Executed: ${cmd}`, "exec");
    consoleInput.value = "";
    vibrate(20);
}

document.getElementById("btn-console-exec").addEventListener("click", executeConsoleCommand);
consoleInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") executeConsoleCommand();
});

document.getElementById("btn-console-clear").addEventListener("click", () => {
    consoleOutput.innerHTML = '<div class="console-line system">Console cleared.</div>';
    vibrate(10);
});

// Quick commands
document.querySelectorAll(".qcmd").forEach(btn => {
    btn.addEventListener("click", () => {
        const cmd = btn.dataset.cmd;
        send({ type: "console_command", command: cmd });
        addConsoleLine(cmd, "user");
        addConsoleLine(`Executed: ${cmd}`, "exec");
        vibrate(15);
    });
});

// Arrow keys and utility keys
document.querySelectorAll(".arrow-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        send({ type: "key_press", key: btn.dataset.key });
        vibrate(15);
    });
});

document.querySelectorAll(".utility-keys .ctrl-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        send({ type: "key_press", key: btn.dataset.key });
        vibrate(15);
    });
});

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
document.getElementById("cursor-sensitivity").addEventListener("input", (e) => {
    const val = parseFloat(e.target.value);
    cursorSensitivity = val;
    document.getElementById("val-cursor-sens").textContent = val.toFixed(1);
    send({ type: "set_sensitivity", value: val });
});

document.getElementById("scroll-sensitivity").addEventListener("input", (e) => {
    const val = parseFloat(e.target.value);
    scrollSensitivity = val;
    document.getElementById("val-scroll-sens").textContent = val.toFixed(1);
    send({ type: "set_scroll_sensitivity", value: val });
});

document.getElementById("btn-precision").addEventListener("click", () => {
    send({ type: "set_precision", value: !document.getElementById("btn-precision").classList.contains("active") });
    vibrate(25);
});

document.getElementById("btn-kill").addEventListener("click", () => {
    send({ type: "pause_resume" });
    vibrate(50);
});

// ---------------------------------------------------------------------------
// Haptic Feedback
// ---------------------------------------------------------------------------
function vibrate(ms) {
    if (window.navigator.vibrate) {
        window.navigator.vibrate(ms);
    }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
connect();
