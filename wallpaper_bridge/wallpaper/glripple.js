// ─────────────────────────────────────────────────────────────────────────────
// glRipple — WebGL displacement renderer for the water-ripple and
// Liquid-Distortion effects.
//
// WHY THIS EXISTS
// The effects were built on an SVG filter chain: a canvas painted the
// displacement map, toDataURL() handed it to <feImage>, and
// <feDisplacementMap> bent #bg with it. Measured in Wallpaper Engine's
// bundled CEF 146, feImage produces nothing at all — 100 % transparent
// output — while every other primitive in the chain works (feFlood
// renders, feDisplacementMap at scale=0 returns the source untouched,
// feTurbulence works). Both data: and blob: URLs fail identically, so it
// is feImage itself, not the hand-off. That is why the effects never
// showed a wave in WE: feDisplacementMap received an empty in2 and
// shredded the image instead of bending it.
//
// WebGL was measured on the same host and matches modern Chromium exactly
// (8 % of pixels displaced, mean luma delta 16.7), running on
// ANGLE / Direct3D11 against the real GPU. So the displacement moves here.
//
// SCOPE — deliberately narrow
// This renders IMAGE backgrounds only. Video backgrounds keep the plain
// #bg path with no effect, which is what WE users have today anyway.
// It does not replace #bg: the div stays, and this canvas sits on top of
// it, showing a displaced copy only while a ripple is in flight. That
// keeps every existing behaviour — the six background-fit modes, tile
// scaling, the cross-fade on image change, and parallax's transform on
// bgEl — untouched and un-reimplemented.
//
// The canvas mirrors #bg's geometry by reading the SAME inputs CSS uses
// (natural image size, viewport, fit mode, tile scale) and computing the
// texture coordinates itself. See computeUV().
// ─────────────────────────────────────────────────────────────────────────────

(function (global) {
  "use strict";

  var VERT = [
    "attribute vec2 aPos;",
    "varying vec2 vUV;",
    "void main() {",
    // Clip space (-1..1) to texture space (0..1), Y flipped so the
    // texture is not upside down.
    "  vUV = vec2(aPos.x * 0.5 + 0.5, 0.5 - aPos.y * 0.5);",
    "  gl_Position = vec4(aPos, 0.0, 1.0);",
    "}"
  ].join("\n");

  var FRAG = [
    "precision mediump float;",
    "varying vec2 vUV;",
    "uniform sampler2D uImage;",   // the background image
    "uniform sampler2D uMap;",     // displacement map (R=x, G=y, 0.5=neutral)
    "uniform vec2  uScale;",       // displacement amount, in UV units
    "uniform vec2  uUVScale;",     // background-size mapping
    "uniform vec2  uUVOffset;",    // background-position mapping
    "uniform float uRepeat;",      // 1.0 = tile, 0.0 = clamp
    "uniform float uAlpha;",
    "void main() {",
    "  vec4 m = texture2D(uMap, vUV);",
    "  vec2 disp = (m.rg - 0.5) * uScale;",
    "  vec2 uv = (vUV + disp) * uUVScale + uUVOffset;",
    "  if (uRepeat < 0.5) {",
    // Outside the image with no repeat: nothing to draw. Matches
    // background-repeat: no-repeat, where the area stays empty.
    "    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {",
    "      gl_FragColor = vec4(0.0);",
    "      return;",
    "    }",
    "  } else {",
    "    uv = fract(uv);",
    "  }",
    "  vec4 c = texture2D(uImage, uv);",
    // Premultiplied: the blend function above expects colour already
    // scaled by alpha. Emitting straight colour here is what made
    // half-transparent pixels twice as bright.
    "  float a = c.a * uAlpha;",
    "  gl_FragColor = vec4(c.rgb * a, a);",
    "}"
  ].join("\n");

  function compile(gl, type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      var log = gl.getShaderInfoLog(s);
      gl.deleteShader(s);
      throw new Error("shader compile failed: " + log);
    }
    return s;
  }

  /**
   * Work out how to sample the image so it lands where CSS would put it.
   *
   * CSS does this with background-size / background-position / repeat on
   * the div. We can't ask the browser for the result, so we recompute it
   * from the same inputs. Returns UV scale + offset for the fragment
   * shader, plus whether to wrap.
   *
   * cover / contain / fill mirror their CSS definitions; tile / tile-x /
   * tile-y follow the sizing formula in BG_FIT_CSS, where the tile is the
   * image's natural size times a percentage.
   */
  function computeUV(fit, tileScale, vw, vh, iw, ih) {
    if (!iw || !ih || !vw || !vh) {
      return { scale: [1, 1], offset: [0, 0], repeat: 0 };
    }
    var s = Math.max(10, Math.min(200, tileScale || 100)) / 100;
    var viewAR = vw / vh, imgAR = iw / ih;
    var sx, sy, repeat = 0;

    switch (fit) {
      case "fill":
        sx = 1; sy = 1;
        break;
      case "contain":
        // Whole image visible; letterboxed on the other axis.
        //
        // The UV scale is "how much of the image we sample across the
        // viewport". Letterboxing means sampling PAST the image edges so
        // the surplus lands outside 0..1 and the shader leaves it
        // transparent — so the scale is > 1 on the letterboxed axis.
        // (cover is the mirror image: it samples a subset, scale < 1.)
        if (imgAR > viewAR) { sx = 1; sy = imgAR / viewAR; }
        else               { sx = viewAR / imgAR; sy = 1; }
        break;
      case "tile":
        sx = vw / (iw * s); sy = vh / (ih * s); repeat = 1;
        break;
      case "tile-x":
        sx = vw / (iw * s); sy = 1; repeat = 1;
        break;
      case "tile-y":
        sx = 1; sy = vh / (ih * s); repeat = 1;
        break;
      case "cover":
      default:
        // Fill the viewport, crop the overflow.
        if (imgAR > viewAR) { sx = viewAR / imgAR; sy = 1; }
        else               { sx = 1; sy = imgAR / viewAR; }
        break;
    }
    // background-position: center center
    return { scale: [sx, sy], offset: [(1 - sx) / 2, (1 - sy) / 2], repeat: repeat };
  }

  function GLRipple(canvas) {
    this.canvas = canvas;
    this.gl = null;
    this.ready = false;
    this.lost = false;
    this.error = null;
    this._imgTex = null;
    this._mapTex = null;
    this._imgSize = { w: 0, h: 0 };
    this._fit = "cover";
    this._tileScale = 100;
    this._onLost = null;
    this._onRestored = null;
  }

  GLRipple.prototype.init = function () {
    var self = this;
    // premultipliedAlpha:true to match what the shader emits. With
    // `false` the browser divides colour by alpha when compositing, and
    // premultiplied output would be darkened by exactly that factor —
    // the mirror image of the brightness bug this pair replaces. The
    // two settings are one decision: shader and context must agree.
    var opts = { alpha: true, premultipliedAlpha: true, antialias: false,
                 depth: false, stencil: false, preserveDrawingBuffer: false };
    var gl = null;
    try {
      gl = this.canvas.getContext("webgl", opts)
        || this.canvas.getContext("experimental-webgl", opts);
    } catch (e) {
      this.error = String(e);
      return false;
    }
    if (!gl) { this.error = "no webgl context"; return false; }
    this.gl = gl;

    // Context loss is a real event on wallpaper hosts — GPU driver
    // updates, sleep/resume, and WE's own suspend all trigger it. Without
    // this the canvas silently goes black and never recovers.
    this.canvas.addEventListener("webglcontextlost", function (e) {
      e.preventDefault();
      self.lost = true;
      self.ready = false;
      if (self._onLost) self._onLost();
    }, false);
    this.canvas.addEventListener("webglcontextrestored", function () {
      self.lost = false;
      try { self._build(); self.ready = true; } catch (err) { self.error = String(err); }
      // _build() nulls _imgTex / _mapTex — the old handles belonged to
      // the dead context. Nothing in here can re-upload the background
      // (only the page knows its URL), so tell the owner to do it.
      // Without this the effects stay dark forever: draw() keeps
      // returning false because _imgTex is null, and the page never
      // learns it has to act.
      if (self._onRestored) self._onRestored();
    }, false);

    try { this._build(); } catch (e) { this.error = String(e); return false; }
    this.ready = true;
    return true;
  };

  GLRipple.prototype._build = function () {
    var gl = this.gl;
    var vs = compile(gl, gl.VERTEX_SHADER, VERT);
    var fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
    var p = gl.createProgram();
    gl.attachShader(p, vs); gl.attachShader(p, fs); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      throw new Error("link failed: " + gl.getProgramInfoLog(p));
    }
    gl.deleteShader(vs); gl.deleteShader(fs);
    this.prog = p;
    gl.useProgram(p);

    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(p, "aPos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    this.u = {
      image:    gl.getUniformLocation(p, "uImage"),
      map:      gl.getUniformLocation(p, "uMap"),
      scale:    gl.getUniformLocation(p, "uScale"),
      uvScale:  gl.getUniformLocation(p, "uUVScale"),
      uvOffset: gl.getUniformLocation(p, "uUVOffset"),
      repeat:   gl.getUniformLocation(p, "uRepeat"),
      alpha:    gl.getUniformLocation(p, "uAlpha")
    };
    gl.uniform1i(this.u.image, 0);
    gl.uniform1i(this.u.map, 1);
    gl.enable(gl.BLEND);
    // v2.4.4-beta.30: separate blending, and premultiplied colour.
    //
    // The old SRC_ALPHA / ONE_MINUS_SRC_ALPHA pair multiplied alpha by
    // itself: clearing to (0,0,0,0) and blending a pixel (rgb, a) left
    // rgb*a in colour but a*a in alpha. The context is created with
    // premultipliedAlpha:false, so the browser divides colour by alpha
    // when compositing — (rgb*a)/(a*a) = rgb/a, i.e. a half-transparent
    // pixel came out twice as bright.
    //
    // Invisible on a fully opaque background, which is why it survived:
    // at a=1 the error term is 1. Every background with soft edges or a
    // transparent region showed it as a brightness lift for as long as
    // water ripple or Liquid Distortion was animating. Reported as
    // "wasserwelle führt nun auf 2ten Monitor wieder dazu das es heller
    // ist ... während der animation".
    //
    // ONE for the colour term because the shader now emits premultiplied
    // colour; alpha keeps ONE_MINUS_SRC_ALPHA so overlapping draws still
    // accumulate coverage correctly.
    gl.blendFuncSeparate(gl.ONE, gl.ONE_MINUS_SRC_ALPHA,
                         gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    this._imgTex = null;
    this._mapTex = null;
  };

  GLRipple.prototype._tex = function (unit, existing, source, wrap) {
    var gl = this.gl;
    var t = existing || gl.createTexture();
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, wrap);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wrap);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
    return t;
  };

  /**
   * Hand over the background image. `img` must be a loaded HTMLImageElement
   * (or anything texImage2D accepts). Non-power-of-two images are fine
   * because we always CLAMP or handle repeat in the shader with fract().
   */
  GLRipple.prototype.setImage = function (img, naturalW, naturalH) {
    if (!this.ready || this.lost) return false;
    try {
      this._imgTex = this._tex(0, this._imgTex, img, this.gl.CLAMP_TO_EDGE);
      this._imgSize = { w: naturalW || img.naturalWidth || img.width,
                        h: naturalH || img.naturalHeight || img.height };
      return true;
    } catch (e) { this.error = String(e); return false; }
  };

  GLRipple.prototype.setFit = function (fit, tileScale) {
    this._fit = fit || "cover";
    this._tileScale = tileScale || 100;
  };

  GLRipple.prototype.setMap = function (mapCanvas) {
    if (!this.ready || this.lost) return false;
    try {
      this._mapTex = this._tex(1, this._mapTex, mapCanvas, this.gl.CLAMP_TO_EDGE);
      return true;
    } catch (e) { this.error = String(e); return false; }
  };

  GLRipple.prototype.resize = function (w, h) {
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w; this.canvas.height = h;
    }
  };

  /**
   * @param ampX,ampY  displacement in CSS pixels (converted to UV here so
   *                   callers can think in the same units the SVG filter's
   *                   `scale` used)
   * @param alpha      0..1, lets the caller fade the effect in and out
   */
  GLRipple.prototype.draw = function (ampX, ampY, alpha) {
    if (!this.ready || this.lost || !this._imgTex || !this._mapTex) return false;
    var gl = this.gl;
    var w = this.canvas.width, h = this.canvas.height;
    var uv = computeUV(this._fit, this._tileScale, w, h,
                       this._imgSize.w, this._imgSize.h);
    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.prog);
    gl.uniform2f(this.u.scale, (ampX || 0) / w, (ampY || 0) / h);
    gl.uniform2f(this.u.uvScale, uv.scale[0], uv.scale[1]);
    gl.uniform2f(this.u.uvOffset, uv.offset[0], uv.offset[1]);
    gl.uniform1f(this.u.repeat, uv.repeat);
    gl.uniform1f(this.u.alpha, alpha === undefined ? 1 : alpha);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this._imgTex);
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, this._mapTex);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    return gl.getError() === gl.NO_ERROR;
  };

  GLRipple.prototype.onContextLost = function (fn) { this._onLost = fn; };
  GLRipple.prototype.onContextRestored = function (fn) { this._onRestored = fn; };

  GLRipple.prototype.destroy = function () {
    var gl = this.gl;
    if (!gl) return;
    try {
      if (this._imgTex) gl.deleteTexture(this._imgTex);
      if (this._mapTex) gl.deleteTexture(this._mapTex);
      if (this.prog) gl.deleteProgram(this.prog);
      var ext = gl.getExtension("WEBGL_lose_context");
      if (ext) ext.loseContext();
    } catch (e) {}
    this.ready = false;
  };

  global.GLRipple = GLRipple;
  global.GLRipple.computeUV = computeUV;   // exported for tests
})(window);
