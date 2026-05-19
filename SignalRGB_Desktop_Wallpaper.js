// SignalRGB Desktop Wallpaper plugin (multi-screen).
//
// Announces 1..3 virtual controllers ("Desktop Wallpaper - Screen N"), one
// per monitor the user wants to drive. Each controller is a distinct device
// in SignalRGB so the user can place them at different canvas positions and
// they'll pull different effect colours. Each device sends its own UDP
// stream to the bridge with a screen-index byte tagging which screen the
// frame is for.
//
// Wire format (per UDP datagram, one frame):
//   bytes 0..1   magic "SR"            (0x53 0x52)
//   byte  2      screen index (u8)     0..2
//   bytes 3..4   width  (u16 big-endian)
//   bytes 5..6   height (u16 big-endian)
//   bytes 7..    width*height RGB triplets, row-major
//
// The bridge fans these frames out to WebSocket clients keyed by ?screen=N.

import udp from "@SignalRGB/udp";

const ICON_DATA_URI = "data:image/svg+xml;utf8,"
    + "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
    +   "<rect x='6' y='8' width='52' height='34' rx='3' fill='%231b1f2a' stroke='%234a5160' stroke-width='2'/>"
    +   "<rect x='10' y='12' width='44' height='26' fill='%23050608'/>"
    +   "<circle cx='17' cy='28' r='3' fill='%23ff2d6a'/>"
    +   "<circle cx='25' cy='28' r='3' fill='%23ff8f2d'/>"
    +   "<circle cx='33' cy='28' r='3' fill='%23ffe92d'/>"
    +   "<circle cx='41' cy='28' r='3' fill='%2342ff85'/>"
    +   "<circle cx='49' cy='28' r='3' fill='%232db4ff'/>"
    +   "<rect x='26' y='46' width='12' height='3' fill='%234a5160'/>"
    +   "<rect x='20' y='50' width='24' height='2' fill='%234a5160'/>"
    + "</svg>";

export function Name()                { return "SignalRGB Desktop Wallpaper"; }
export function Version()             { return "0.2.0"; }
export function Type()                { return "network"; }
export function Publisher()           { return "Delido"; }
export function Size()                { return [32, 32]; }
export function DefaultPosition()     { return [50, 50]; }
export function DefaultScale()        { return 60.0; }
export function SubdeviceController() { return false; }
export function ImageUrl()            { return ICON_DATA_URI; }

/* global
controller:readonly
discovery:readonly
gridSize:readonly
LightingMode:readonly
forcedColor:readonly
shutdownColor:readonly
targetFps:readonly
bridgePort:readonly
*/

const MAX_SCREENS  = 3;
// 36×36 is the largest square that fits SignalRGB's per-packet udp.send
// cap of 4096 bytes (36*36*3 + 7-byte header = 3895 B). Going higher
// requires chunking the frame across multiple datagrams — see the
// CHANGELOG for v0.6.2-beta's failed bump to 64.
const MAX_GRID     = 36;
const BRIDGE_HOST  = "127.0.0.1";
const BRIDGE_PORT  = 17320;
const CONFIG_URL   = "http://" + BRIDGE_HOST + ":" + BRIDGE_PORT + "/config";

// The number of controllers we expose is owned by the BRIDGE (config.json,
// editable via the tray's Settings dialog). SignalRGB's ControllableParameters
// are device-scoped — they can't drive discovery-time decisions — so we
// resolve the chicken-and-egg by having DiscoveryService.Update() XHR the
// bridge's /config endpoint and follow whatever number it reports. If the
// bridge is offline we fall back to MAX_SCREENS so single-screen and bridge-
// never-installed setups still work.

export function ControllableParameters() {
    return [
        {"property":"gridSize", "group":"settings", "label":"Glow Grid Size",
         "description":"Square grid resolution sent per screen. 36 is the finest that fits SignalRGB's 4 KB per-packet UDP cap; 32 is the previous default; lower values are kinder on older machines.",
         "type":"combobox", "values":["8","16","32","36"], "default":"32"},
        {"property":"targetFps", "group":"settings", "label":"Target FPS",
         "description":"Frame rate the engine should call Render() at. 30 is plenty for ambient lighting; 60 is the engine's hard cap.",
         "type":"combobox", "values":["15","30","60"], "default":"30"},
        {"property":"bridgePort", "group":"settings", "label":"Bridge UDP Port",
         "description":"UDP port the bridge listens on (default 17320). Change only if you adjusted the bridge.",
         "type":"textfield", "filter":"^[0-9]{1,5}$", "default":"17320"},
        {"property":"LightingMode", "group":"lighting", "label":"Lighting Mode",
         "description":"Canvas pulls from the active SignalRGB effect. Forced overrides with a single color.",
         "type":"combobox", "values":["Canvas","Forced"], "default":"Canvas"},
        {"property":"forcedColor", "group":"lighting", "label":"Forced Color",
         "description":"Color used when Lighting Mode is set to Forced.",
         "min":"0", "max":"360", "type":"color", "default":"#009bde"},
        {"property":"shutdownColor", "group":"lighting", "label":"Shutdown Color",
         "description":"Frame sent when SignalRGB or the device is shutting down.",
         "min":"0", "max":"360", "type":"color", "default":"#000000"},
    ];
}

// `typeof` guards because SignalRGB throws ReferenceError on undeclared
// globals, and ControllableParameters values may not be wired up the
// first time Initialize() runs.
function gridSizeValue()     { return clampInt(typeof gridSize     !== "undefined" ? parseInt(gridSize)     : 32, 1, MAX_GRID); }
function targetFpsValue()    { return            typeof targetFps    !== "undefined" ? parseInt(targetFps)    : 30; }
function bridgePortValue()   { return            typeof bridgePort   !== "undefined" ? parseInt(bridgePort)   : 17320; }
function lightingModeValue() { return            typeof LightingMode !== "undefined" ? LightingMode           : "Canvas"; }
function forcedColorValue()  { return            typeof forcedColor  !== "undefined" ? forcedColor            : "#000000"; }
function shutdownColorValue(){ return            typeof shutdownColor !== "undefined" ? shutdownColor         : "#000000"; }

function clampInt(v, lo, hi) { v = isNaN(v) ? lo : v; return Math.max(lo, Math.min(hi, v)); }

function hexToRgb(hex) {
    const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || "");
    if (!m) return [0, 0, 0];
    return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
}

// ────────────────────────────────────────────────────────────────────────────
// Per-device runtime state.
//
// SignalRGB calls Initialize()/Render()/Shutdown() once per device — multiple
// devices share the JS runtime, so module-globals would collide. We key per
// screenIndex (read from `controller.screenIndex` which we set when the
// controller is announced in DiscoveryService).
// ────────────────────────────────────────────────────────────────────────────

const stateByScreen = new Map();

function currentScreenIndex() {
    return (typeof controller !== "undefined" && controller && typeof controller.screenIndex === "number")
        ? controller.screenIndex
        : 0;
}

function getState() {
    const idx = currentScreenIndex();
    let s = stateByScreen.get(idx);
    if (!s) {
        s = { sock: null, cols: 32, rows: 32, leds: 32 * 32, frameBuf: null,
              renderCount: 0, renderLogAt: 0 };
        stateByScreen.set(idx, s);
    }
    return s;
}

function rebuildFrameBuffer(s, screenIndex) {
    // 7-byte header + W*H*3 RGB bytes
    s.frameBuf = new Array(7 + s.leds * 3);
    s.frameBuf[0] = 0x53; // 'S'
    s.frameBuf[1] = 0x52; // 'R'
    s.frameBuf[2] = screenIndex & 0xff;
    s.frameBuf[3] = (s.cols >> 8) & 0xff;
    s.frameBuf[4] =  s.cols       & 0xff;
    s.frameBuf[5] = (s.rows >> 8) & 0xff;
    s.frameBuf[6] =  s.rows       & 0xff;
}

function applyZoneSize() {
    const s = getState();
    const size = gridSizeValue();
    s.cols = size;
    s.rows = size;
    s.leds = size * size;
    device.setSize([s.cols, s.rows]);
    const names = [];
    const positions = [];
    for (let y = 0; y < s.rows; y++) {
        for (let x = 0; x < s.cols; x++) {
            names.push("Z" + (y * s.cols + x + 1));
            positions.push([x, y]);
        }
    }
    device.setControllableLeds(names, positions);
    rebuildFrameBuffer(s, currentScreenIndex());
    device.log("[DesktopWallpaper] screen " + currentScreenIndex() + " grid " + s.cols + "x" + s.rows);
}

function openSocket() {
    const s = getState();
    if (s.sock) { try { s.sock.close(); } catch (_) {} s.sock = null; }
    s.sock = udp.createSocket();
    try { s.sock.on("error", function (e) { device.log("[DesktopWallpaper] UDP socket error: " + e); }); } catch (_) {}
    try { s.sock.on("connection", function () {}); } catch (_) {}
    try { s.sock.on("message", function () {}); } catch (_) {}
    const port = bridgePortValue();
    s.sock.connect(BRIDGE_HOST, port);
    device.log("[DesktopWallpaper] screen " + currentScreenIndex() + " UDP -> " + BRIDGE_HOST + ":" + port);
}

function applyFrameRateTarget() {
    const fps = targetFpsValue();
    try {
        if (typeof device.setFrameRateTarget === "function") {
            device.setFrameRateTarget(fps);
            device.log("[DesktopWallpaper] setFrameRateTarget(" + fps + ")");
        }
    } catch (e) {
        device.log("[DesktopWallpaper] setFrameRateTarget failed: " + e);
    }
}

export function Initialize() {
    const idx = currentScreenIndex();
    device.log("[DesktopWallpaper] Initialize for screen " + idx);
    device.setName("Desktop Wallpaper - Screen " + (idx + 1));
    try { device.setImageFromUrl(ICON_DATA_URI); } catch (_) {}
    applyZoneSize();
    applyFrameRateTarget();
    openSocket();
}

export function ongridSizeChanged()   { applyZoneSize(); }
export function onbridgePortChanged() { openSocket(); }
export function ontargetFpsChanged()  { applyFrameRateTarget(); }

export function Render() {
    const s = getState();
    if (!s.sock || !s.frameBuf) return;

    // Keep the screen-index byte in sync — if the user reordered screens
    // SignalRGB might invoke us in a different order.
    s.frameBuf[2] = currentScreenIndex() & 0xff;

    const forced = lightingModeValue() === "Forced" ? hexToRgb(forcedColorValue()) : null;
    let off = 7;
    for (let y = 0; y < s.rows; y++) {
        for (let x = 0; x < s.cols; x++) {
            const c = forced || device.color(x, y);
            s.frameBuf[off++] = c[0];
            s.frameBuf[off++] = c[1];
            s.frameBuf[off++] = c[2];
        }
    }
    try {
        s.sock.send(s.frameBuf);
        s.renderCount++;
        const now = Date.now();
        if (s.renderCount === 1 || now - s.renderLogAt > 5000) {
            s.renderLogAt = now;
            device.log("[DesktopWallpaper] screen " + currentScreenIndex()
                + " frame #" + s.renderCount + " grid=" + s.cols + "x" + s.rows
                + " first_rgb=[" + s.frameBuf[7] + "," + s.frameBuf[8] + "," + s.frameBuf[9] + "]");
        }
    } catch (e) {
        device.log("[DesktopWallpaper] UDP send failed: " + e);
    }
    device.pause(1);
}

export function Shutdown(suspend) {
    const s = getState();
    if (!s.sock || !s.frameBuf) return;
    const c = hexToRgb(shutdownColorValue());
    let off = 7;
    for (let i = 0; i < s.leds; i++) {
        s.frameBuf[off++] = c[0];
        s.frameBuf[off++] = c[1];
        s.frameBuf[off++] = c[2];
    }
    try { s.sock.send(s.frameBuf); } catch (_) {}
    try { s.sock.close(); } catch (_) {}
    s.sock = null;
}

// ────────────────────────────────────────────────────────────────────────────
// Discovery: announce N virtual controllers, one per requested screen.
// ────────────────────────────────────────────────────────────────────────────

class VirtualController {
    constructor(screenIndex) {
        this.id           = "signalrgb-desktop-wallpaper-screen-" + screenIndex;
        this.name         = "Desktop Wallpaper - Screen " + (screenIndex + 1);
        this.sku          = "DESKTOP-WP-SCR" + (screenIndex + 1);
        this.ip           = "127.0.0.1";
        this.image        = ICON_DATA_URI;
        this.screenIndex  = screenIndex;
        this.initialized  = false;
    }
    update() {
        if (!this.initialized) {
            this.initialized = true;
            service.log("[DesktopWallpaper] announcing controller for screen " + this.screenIndex);
            service.updateController(this);
            service.announceController(this);
        }
    }
}

export function DiscoveryService() {
    this.IconUrl     = ICON_DATA_URI;
    this.lastEnsure  = 0;
    this.lastCount   = null;   // last value successfully read from bridge
    this.lastCountAt = 0;

    // Sync XHR to the bridge's /config endpoint. Returns 1..MAX_SCREENS on
    // success, or null if the bridge is unreachable / replied with garbage.
    // The plugin sandbox supports synchronous XMLHttpRequest and we want a
    // blocking answer here so ensureControllers can act on it in one tick.
    const fetchScreenCountSync = function () {
        try {
            const xhr = new XMLHttpRequest();
            xhr.open("GET", CONFIG_URL, false);
            xhr.timeout = 500;
            xhr.send(null);
            if (xhr.status === 200) {
                const cfg = JSON.parse(xhr.responseText);
                const n = parseInt(cfg && cfg.screenCount);
                if (isFinite(n) && n >= 1 && n <= MAX_SCREENS) return n;
            }
        } catch (_) {
            // bridge offline / parse error / network blocked — let caller decide
        }
        return null;
    };

    const self = this;
    const desiredScreenCount = function () {
        const now = Date.now();
        // Throttle XHR to once per 2s — Update() runs at engine cadence.
        if (now - self.lastCountAt < 2000 && self.lastCount !== null) {
            return self.lastCount;
        }
        self.lastCountAt = now;
        const fetched = fetchScreenCountSync();
        if (fetched !== null) {
            if (fetched !== self.lastCount) {
                service.log("[DesktopWallpaper] bridge /config -> screenCount=" + fetched);
            }
            self.lastCount = fetched;
            return fetched;
        }
        // Bridge unreachable: keep last good value, or show all 3 as a safe
        // visible-but-not-broken default until the bridge comes online.
        return self.lastCount !== null ? self.lastCount : MAX_SCREENS;
    };

    this.ensureControllers = function () {
        const wanted = desiredScreenCount();
        for (let i = 0; i < wanted; i++) {
            const id = "signalrgb-desktop-wallpaper-screen-" + i;
            if (service.getController(id) === undefined) {
                service.log("[DesktopWallpaper] adding virtual controller for screen " + i);
                service.addController(new VirtualController(i));
            }
        }
        // Drop excess controllers if the user reduced the count via the tray.
        // service.removeController takes the controller wrapper returned by
        // getController. Wrapped in try/catch since some SignalRGB builds may
        // not expose removeController — better to log and continue.
        for (let i = wanted; i < MAX_SCREENS; i++) {
            const id = "signalrgb-desktop-wallpaper-screen-" + i;
            const existing = service.getController(id);
            if (existing !== undefined) {
                try {
                    service.removeController(existing);
                    service.log("[DesktopWallpaper] removed virtual controller for screen " + i + " (screenCount=" + wanted + ")");
                } catch (e) {
                    service.log("[DesktopWallpaper] removeController for screen " + i + " failed: " + e);
                }
            }
        }
    };

    this.Initialize = function () {
        service.log("[DesktopWallpaper] DiscoveryService.Initialize fired");
        this.ensureControllers();
    };

    this.Update = function () {
        for (const cont of service.controllers) {
            if (cont && cont.obj && typeof cont.obj.update === "function") {
                cont.obj.update();
            }
        }
        const now = Date.now();
        if (now - this.lastEnsure < 2000) return;
        this.lastEnsure = now;
        this.ensureControllers();
    };

    this.Shutdown = function () {};
    this.Discovered = function () {};
    this.Removal = function () {};
}
