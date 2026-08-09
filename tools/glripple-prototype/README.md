# glRipple — WebGL displacement prototype

Not wired into the wallpaper. This is a measured, working replacement for
the SVG-filter path behind water-ripple and Liquid Distortion, kept here
so the investigation behind it isn't lost.

## Why

Those two effects have never worked in Wallpaper Engine. The source
blamed a colour-space mismatch; measurement in WE's bundled CEF 146
showed something else entirely:

| Primitive | Chromium 151 | WE CEF 146 |
|---|---|---|
| `feFlood` | renders | renders |
| `feDisplacementMap` @ scale=0 | source unchanged | source unchanged |
| **`feImage` output** | olive (128,128,0) | **rgba(0,0,0,0), 100 % transparent** |

`feImage` yields nothing, so `feDisplacementMap` gets an empty `in2` and
shreds the image instead of bending it — the "shift on click, but never a
wave" users reported. `data:` and `blob:` URLs fail identically, and a
sweep of the map's neutral byte (R=100…220) returned the same result for
every value, which rules out a colour-space cause.

WebGL was measured on the same host and works:

- **ANGLE (NVIDIA GeForce RTX 4070 Ti) Direct3D11** — real GPU, WebGL2 available
- **0.36 ms/frame** for map paint + texture upload + draw (~1 % of a 33 ms budget)
- Removes the 30 `toDataURL()` calls per second the current path makes

## Geometry accuracy

`computeUV()` reproduces the six CSS background-fit modes. Pixel-diffed
against a Canvas2D reference, identical on both hosts:

| Fit | Chromium 151 | WE CEF 146 |
|---|---|---|
| cover | 0 % | 0 % |
| contain | 1 % | 1 % |
| fill | 0 % | 0 % |
| tile | 3 % | 3 % |
| tile-x | 3 % | 3 % |
| tile-y | 0 % | 0 % |

## Running the bench

Open `test-bench.html` in a browser, or drop this folder into
`…/wallpaper_engine/projects/myprojects/` with a `project.json` to run it
as a wallpaper. Each fit mode shows CSS and WebGL side by side; the live
panel spawns a ripple on click.

Two caveats learned building it, worth keeping in mind if you extend the
bench:

- The first test image was a fine white grid. At 150×84 those lines are
  ~1 px wide, so ~13 % of pixels sit on an edge and any half-pixel
  sampling difference flips them — it reported 10–32 % "mismatch" with no
  geometry error at all. Use low-frequency content.
- CSS `background-repeat` with `background-position: center` centres **one
  tile** and repeats outward, not the whole grid. Getting that wrong in
  the reference shifts everything by up to half a tile.

## What integration still needs

- Wiring to `setBackground()`, including the cross-fade on image change
- Coexistence with `parallax`, which already writes `bgEl.style.transform`
- Video backgrounds: effect stays off (deliberate scope limit)
- Resize / DPR handling against the real viewport
- Fallback to the current SVG path where WebGL is unavailable
