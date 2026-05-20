// SignalRGB Desktop Wallpaper plugin (multi-screen).
//
// Announces 1..4 virtual controllers ("Desktop Wallpaper - Screen N"), one
// per monitor the user wants to drive. Each controller is a distinct device
// in SignalRGB so the user can place them at different canvas positions and
// they'll pull different effect colours. Each device sends its own UDP
// stream to the bridge with a screen-index byte tagging which screen the
// frame is for.
//
// Wire format (per UDP datagram, one frame):
//   bytes 0..1   magic "SR"            (0x53 0x52)
//   byte  2      screen index (u8)     0..3
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
// Size() declares the device's *visual aspect ratio* in SignalRGB's
// layout editor — only the ratio matters, not the absolute numbers.
// SignalRGB locks the on-canvas bounding box to this ratio, so any
// runtime device.setSize() with a different ratio gets visually
// stretched (the LED count is still right, but each cell looks
// squashed). 16:9 is the dominant monitor aspect, so we ship it as
// the default. Users on 1:1 / 21:9 / 32:9 / 9:16 will still see
// rectangular cells in the canvas, but the actual glow output to the
// wallpaper page is unaffected — only the SignalRGB-editor preview is.
export function Size()                { return [16, 9]; }
export function DefaultPosition()     { return [50, 50]; }
export function DefaultScale()        { return 1.0; }
export function SubdeviceController() { return false; }
export function ImageUrl()            { return ICON_DATA_URI; }

/* global
controller:readonly
discovery:readonly
gridSize:readonly
aspectRatio:readonly
customCols:readonly
customRows:readonly
LightingMode:readonly
forcedColor:readonly
shutdownColor:readonly
targetFps:readonly
bridgePort:readonly
*/

const MAX_SCREENS  = 4;
// Per-packet UDP cap inside SignalRGB's plugin sandbox. Real fixed limit
// is 4096 B; we shave off 4 bytes of headroom so we never tickle the
// boundary if the engine validates strictly.
const UDP_MAX_PAYLOAD = 4092;
// 36×36 still fits the cap in a single packet via the original "SR" wire
// format (36*36*3 + 7 = 3895 B). Anything larger uses the chunked "SC"
// format below — each datagram carries a piece of the frame, the bridge
// reassembles before broadcasting to wallpaper pages.
const MAX_GRID     = 128;
// SC chunk header: 12 bytes. See the bridge for the layout. With
// 4092-byte UDP budget that leaves 4080 bytes = 1360 pixels per chunk.
const SC_HEADER_BYTES   = 12;
const SC_MAX_CHUNK_PX   = Math.floor((UDP_MAX_PAYLOAD - SC_HEADER_BYTES) / 3);
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
        {"property":"gridSize", "group":"settings", "label":"Glow Grid Base Size",
         "description":"Shorter-side resolution of the glow grid (rows for landscape aspect ratios, cols for portrait). The other side is derived from Aspect Ratio. 36 base is the largest that fits SignalRGB's 4 KB UDP cap in a single packet; 64 / 96 / 128 use the bridge's chunked transport (each frame split across multiple datagrams, reassembled before reaching the wallpaper).",
         "type":"combobox", "values":["8","16","32","36","64","96","128"], "default":"32"},
        {"property":"aspectRatio", "group":"settings", "label":"Aspect Ratio",
         "description":"Shape of the glow grid. Auto reads each monitor's actual viewport from the bridge (set automatically the first time a wallpaper page connects). 1:1 keeps the legacy square behaviour. 16:9 widescreen / 21:9 ultrawide / 32:9 super-ultrawide / 9:16 portrait force a fixed shape. Custom uses the Custom Cols × Rows fields below.",
         "type":"combobox", "values":["Auto","1:1","16:9","21:9","32:9","9:16","Custom"], "default":"Auto"},
        {"property":"customCols", "group":"settings", "label":"Custom Cols",
         "description":"Number of columns when Aspect Ratio = Custom (1..128). Ignored otherwise.",
         "type":"textfield", "filter":"^[0-9]{1,3}$", "default":"32"},
        {"property":"customRows", "group":"settings", "label":"Custom Rows",
         "description":"Number of rows when Aspect Ratio = Custom (1..128). Ignored otherwise.",
         "type":"textfield", "filter":"^[0-9]{1,3}$", "default":"32"},
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
function aspectRatioValue()  { return            typeof aspectRatio  !== "undefined" ? aspectRatio           : "Auto"; }
function customColsValue()   { return clampInt(typeof customCols    !== "undefined" ? parseInt(customCols)   : 32, 1, MAX_GRID); }
function customRowsValue()   { return clampInt(typeof customRows    !== "undefined" ? parseInt(customRows)   : 32, 1, MAX_GRID); }
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
              renderCount: 0, renderLogAt: 0,
              // Chunked-frame transport: frameId cycles 0..255 so the bridge
              // can identify which chunks belong together when packets arrive
              // out-of-order, and discard partial frames from a stale id.
              frameId: 0 };
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

// Viewport sizes published by the bridge via GET /config. Updated by
// DiscoveryService each time it polls (every ~2 s) and read by
// computeGridDimensions when Aspect Ratio = Auto.
const viewportsByScreen = [];

// Resolve the {cols, rows} the plugin should currently send. The "base
// size" combobox (8/16/32/36/64/96/128) controls the SHORTER side; the
// longer side is derived from the chosen aspect ratio so an ultrawide
// monitor stops getting a square grid that under-samples its width.
function computeGridDimensions() {
    const base = gridSizeValue();
    const aspect = aspectRatioValue();
    if (aspect === "Custom") {
        return { cols: customColsValue(), rows: customRowsValue() };
    }
    if (aspect === "1:1") {
        return { cols: base, rows: base };
    }
    let w = 16, h = 9;   // default 16:9 fallback (also: "Auto" with no viewport yet)
    if      (aspect === "16:9") { w = 16; h = 9; }
    else if (aspect === "21:9") { w = 21; h = 9; }
    else if (aspect === "32:9") { w = 32; h = 9; }
    else if (aspect === "9:16") { w = 9;  h = 16; }
    else if (aspect === "Auto") {
        const v = viewportsByScreen[currentScreenIndex()];
        if (v && v.w > 0 && v.h > 0) { w = v.w; h = v.h; }
    }
    let cols, rows;
    if (w >= h) {
        rows = base;
        cols = Math.max(1, Math.round(base * w / h));
    } else {
        cols = base;
        rows = Math.max(1, Math.round(base * h / w));
    }
    return { cols: clampInt(cols, 1, MAX_GRID), rows: clampInt(rows, 1, MAX_GRID) };
}

function applyZoneSize() {
    const s = getState();
    const dims = computeGridDimensions();
    s.cols = dims.cols;
    s.rows = dims.rows;
    s.leds = s.cols * s.rows;
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
    device.log("[DesktopWallpaper] screen " + currentScreenIndex() + " grid " + s.cols + "x" + s.rows
               + " (aspect=" + aspectRatioValue() + ")");
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

export function ongridSizeChanged()     { applyZoneSize(); }
export function onaspectRatioChanged()  { applyZoneSize(); }
export function oncustomColsChanged()   { applyZoneSize(); }
export function oncustomRowsChanged()   { applyZoneSize(); }
export function onbridgePortChanged()   { openSocket(); }
export function ontargetFpsChanged()    { applyFrameRateTarget(); }

export function Render() {
    const s = getState();
    if (!s.sock || !s.frameBuf) return;

    // Cheap O(1) re-check: when Aspect Ratio = Auto and the bridge just
    // published a fresh viewport for this screen, we rebuild the grid here
    // — SignalRGB doesn't fire onChanged events for state that lives
    // outside ControllableParameters, so we react on the next tick instead.
    const want = computeGridDimensions();
    if (want.cols !== s.cols || want.rows !== s.rows) {
        applyZoneSize();
    }

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

    const totalSize = 7 + s.leds * 3;
    try {
        if (totalSize <= UDP_MAX_PAYLOAD) {
            // Fits in one packet → original "SR" wire format, unchanged. The
            // bridge still recognises this and forwards it verbatim.
            s.sock.send(s.frameBuf);
        } else {
            // Too big for a single datagram → use the chunked "SC" format.
            sendChunkedFrame(s);
        }
        s.renderCount++;
        const now = Date.now();
        if (s.renderCount === 1 || now - s.renderLogAt > 5000) {
            s.renderLogAt = now;
            const tag = (totalSize <= UDP_MAX_PAYLOAD) ? "single" : "chunked";
            device.log("[DesktopWallpaper] screen " + currentScreenIndex()
                + " frame #" + s.renderCount + " grid=" + s.cols + "x" + s.rows
                + " (" + tag + ", " + totalSize + " B)");
        }
    } catch (e) {
        device.log("[DesktopWallpaper] UDP send failed: " + e);
    }
    device.pause(1);
}

// Split the frame buffer across multiple datagrams using the SC wire format.
// Each chunk is ≤ UDP_MAX_PAYLOAD bytes and carries:
//   [0x53][0x43][screen][frameId][chunkIdx][chunkCount]
//   [wH][wL][hH][hL][pixelOffsetH][pixelOffsetL]   (12 bytes total)
//   [rgb …]
// The bridge buffers chunks by (screen, frameId) and only forwards once
// every chunkIdx 0..chunkCount-1 has arrived.
function sendChunkedFrame(s) {
    s.frameId = (s.frameId + 1) & 0xff;
    const totalPixels    = s.leds;
    const pixelsPerChunk = SC_MAX_CHUNK_PX;
    const chunkCount     = Math.ceil(totalPixels / pixelsPerChunk);
    const screenIdx      = currentScreenIndex() & 0xff;
    for (let c = 0; c < chunkCount; c++) {
        const pixelOffset   = c * pixelsPerChunk;
        const pixelsInChunk = Math.min(pixelsPerChunk, totalPixels - pixelOffset);
        const payloadBytes  = pixelsInChunk * 3;
        const pkt = new Array(SC_HEADER_BYTES + payloadBytes);
        pkt[0]  = 0x53; // 'S'
        pkt[1]  = 0x43; // 'C' — chunked magic
        pkt[2]  = screenIdx;
        pkt[3]  = s.frameId;
        pkt[4]  = c;
        pkt[5]  = chunkCount;
        pkt[6]  = (s.cols >> 8) & 0xff;
        pkt[7]  =  s.cols       & 0xff;
        pkt[8]  = (s.rows >> 8) & 0xff;
        pkt[9]  =  s.rows       & 0xff;
        pkt[10] = (pixelOffset >> 8) & 0xff;
        pkt[11] =  pixelOffset       & 0xff;
        // Splice the RGB slice out of s.frameBuf (which still has the old
        // 7-byte SR header, so source starts at byte 7 + pixelOffset*3).
        const srcStart = 7 + pixelOffset * 3;
        for (let i = 0; i < payloadBytes; i++) {
            pkt[SC_HEADER_BYTES + i] = s.frameBuf[srcStart + i];
        }
        s.sock.send(pkt);
    }
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
                // Sidecar: bridge publishes each screen's last-known viewport
                // (set when a wallpaper page opens its WS) so the plugin's
                // Aspect Ratio = Auto can derive cols/rows from the real
                // monitor instead of assuming 16:9.
                if (cfg && Array.isArray(cfg.screens)) {
                    for (let i = 0; i < cfg.screens.length; i++) {
                        const v = cfg.screens[i] || {};
                        const w = parseInt(v.viewportW) | 0;
                        const h = parseInt(v.viewportH) | 0;
                        viewportsByScreen[i] = (w > 0 && h > 0) ? { w, h } : null;
                    }
                }
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
