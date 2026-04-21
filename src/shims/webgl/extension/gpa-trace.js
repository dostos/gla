// gpa-trace.js — Phase 1 of `gpa trace` (see
// docs/superpowers/specs/2026-04-20-gpa-trace-design.md).
//
// Reflection scanner that, on each uniform/bindTexture call (in gated
// mode), BFS-walks registered JS globals, hashes primitive values, and
// POSTs a value_index to the OpenGPA engine sidecar.
//
// Intentionally orthogonal to interceptor.js — the only shared state is
// window.__gpaState.{frameId, dcCount} which interceptor.js exposes.

(function () {
  'use strict';

  // ---- config --------------------------------------------------------
  var DEFAULT_ROOTS = ['THREE', 'mapboxgl', 'PIXI', 'scene', 'map',
                       'renderer', 'camera', 'app'];
  var DEFAULT_DEPTH = 4;
  var MIN_DEPTH = 2;
  var MAX_OBJECTS = 1000;
  var BUDGET_MS = 2.0;
  var SECRET_RE = /token|apikey|api_key|password|secret|bearer/i;
  // POST target — relative to the engine's REST API. Hardcoded to the
  // common dev port; users override via localStorage.GPA_TRACE_ENDPOINT.
  var DEFAULT_ENDPOINT = 'http://127.0.0.1:18080/api/v1';

  // ---- state ---------------------------------------------------------
  var enabled = false;
  var mode = 'gated';
  var roots = [];             // [{obj, name}]
  var depthCap = DEFAULT_DEPTH;
  var endpoint = DEFAULT_ENDPOINT;
  var authToken = '';
  var patched = false;

  // ---- hashing -------------------------------------------------------
  function djb2(s) {
    var h = 5381;
    for (var i = 0; i < s.length; i++) {
      h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    }
    return (h >>> 0).toString(36);
  }

  // Canonical cross-origin numeric hash. Must match the C shim in
  // src/shims/gl/native_trace.c::number_to_js_base36 and the Python
  // parser in src/python/gpa/api/routes_trace.py::_parse_canonical_number.
  // Format:
  //   NaN           -> "n:NaN"
  //   +/- Infinity  -> "n:Inf" / "n:-Inf"
  //   zero / -0     -> "n:0"
  //   safe integer  -> "n:<signed-decimal>"      (|v| < 2^53)
  //   other finite  -> "n:f:<16 hex bits>"       (IEEE-754 big-endian)
  // Base-36 (the previous format) diverged between V8 and C printf for
  // fractional values, so cross-origin value matching silently failed.
  function canonicalNumber(v) {
    if (v !== v) return 'NaN';
    if (v === Infinity) return 'Inf';
    if (v === -Infinity) return '-Inf';
    if (v === 0) return '0';
    if (Number.isInteger(v) && Math.abs(v) < 9007199254740992) {
      return v.toString(10);
    }
    // IEEE-754 bit pattern (big-endian) → lowercase hex.
    var buf = new ArrayBuffer(8);
    new Float64Array(buf)[0] = v;
    var u8 = new Uint8Array(buf);
    var out = 'f:';
    // Little-endian architectures (the common case): reverse the byte order
    // so the hex is always big-endian irrespective of the host.
    for (var i = 7; i >= 0; i--) {
      var b = u8[i];
      out += (b < 16 ? '0' : '') + b.toString(16);
    }
    return out;
  }

  function hashValue(v) {
    var t = typeof v;
    if (t === 'number') {
      return 'n:' + canonicalNumber(v);
    }
    if (t === 'string') return 's:' + djb2(v.toLowerCase());
    if (t === 'boolean') return 'b:' + (v ? '1' : '0');
    if (Array.isArray(v)) {
      try { return 'a:' + djb2(JSON.stringify(v)); }
      catch (_) { return null; }
    }
    return null;
  }

  function typeOf(v) {
    if (Array.isArray(v)) return 'array';
    return typeof v;
  }

  function isTrivial(v) {
    return v === 0 || v === 1 || v === '' || v === true || v === false;
  }

  // ---- filters -------------------------------------------------------
  function isDomNode(o) {
    return typeof Node !== 'undefined' && o instanceof Node;
  }

  function isBigTypedArray(o) {
    return ArrayBuffer.isView(o) && !(o instanceof DataView) &&
           o.length > 1024;
  }

  function isSmallPrimArray(o) {
    if (!Array.isArray(o) || o.length > 16) return false;
    for (var i = 0; i < o.length; i++) {
      var t = typeof o[i];
      if (t !== 'number' && t !== 'string' && t !== 'boolean') return false;
    }
    return true;
  }

  function shouldSkipKey(key, depth) {
    if (typeof key !== 'string') return false;
    if (depth > 1 && key.charAt(0) === '_') return true;
    return false;
  }

  // ---- scanner -------------------------------------------------------
  // Visits `roots` BFS, assembling {hash: [{path, type, confidence}]}.
  // Returns {value_index, truncated, scan_ms, scanned}.
  function scan() {
    var start = (typeof performance !== 'undefined' && performance.now)
                ? performance.now() : Date.now();
    var valueIndex = {};
    var seen = typeof WeakSet !== 'undefined' ? new WeakSet() : null;
    var queue = [];
    var scanned = 0;
    var truncated = false;

    for (var i = 0; i < roots.length; i++) {
      var r = roots[i];
      if (r.obj && typeof r.obj === 'object') {
        queue.push({ o: r.obj, path: r.name, d: 0 });
      }
    }

    function addEntry(hash, path, vtype, confidence) {
      if (!hash) return;
      if (!valueIndex[hash]) valueIndex[hash] = [];
      valueIndex[hash].push({
        path: path,
        type: vtype,
        confidence: confidence,
      });
    }

    while (queue.length) {
      if (scanned >= MAX_OBJECTS) { truncated = true; break; }
      var now = (typeof performance !== 'undefined' && performance.now)
                ? performance.now() : Date.now();
      if (now - start > BUDGET_MS) { truncated = true; break; }

      var item = queue.shift();
      var obj = item.o;
      var basePath = item.path;
      var depth = item.d;
      scanned++;

      if (seen) {
        if (seen.has(obj)) continue;
        try { seen.add(obj); } catch (_) { /* non-extensible */ }
      }

      // Enumerate direct keys only (no prototype walk).
      var keys;
      try { keys = Object.keys(obj); } catch (_) { continue; }
      for (var k = 0; k < keys.length; k++) {
        var key = keys[k];
        if (shouldSkipKey(key, depth)) continue;
        var path = basePath + '.' + key;
        if (SECRET_RE.test(path)) continue;
        var val;
        try { val = obj[key]; } catch (_) { continue; }
        if (val === null || val === undefined) continue;

        var vt = typeof val;
        if (vt === 'function') continue;

        if (vt === 'number' || vt === 'string' || vt === 'boolean') {
          var h = hashValue(val);
          addEntry(h, path, vt, isTrivial(val) ? 'low' : 'high');
          continue;
        }

        if (isSmallPrimArray(val)) {
          var ah = hashValue(val);
          addEntry(ah, path, 'array', 'high');
          continue;
        }

        if (vt !== 'object') continue;
        if (isDomNode(val)) continue;
        if (isBigTypedArray(val)) continue;

        if (depth + 1 < depthCap) {
          queue.push({ o: val, path: path, d: depth + 1 });
        }
      }
    }

    var end = (typeof performance !== 'undefined' && performance.now)
              ? performance.now() : Date.now();
    return {
      value_index: valueIndex,
      truncated: truncated,
      scan_ms: +(end - start).toFixed(3),
      scanned: scanned,
    };
  }

  // ---- transport -----------------------------------------------------
  function postSources(frameId, dcId, result) {
    var payload = {
      frame_id: frameId,
      dc_id: dcId,
      sources: {
        roots: roots.map(function (r) { return r.name; }),
        mode: mode,
        value_index: result.value_index,
        truncated: result.truncated,
        scan_ms: result.scan_ms,
      },
    };
    try {
      var url = endpoint +
                '/frames/' + frameId + '/drawcalls/' + dcId + '/sources';
      var headers = { 'Content-Type': 'application/json' };
      if (authToken) headers['Authorization'] = 'Bearer ' + authToken;
      // fetch with keepalive so a late scan on pagehide still ships.
      fetch(url, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(payload),
        keepalive: true,
      }).catch(function () { /* engine may not be up; swallow. */ });
    } catch (_) { /* no fetch available, give up. */ }
  }

  // ---- hook ----------------------------------------------------------
  // Fired synchronously from the patched gl.uniform* / bindTexture.
  function onGatedCall() {
    if (!enabled || mode !== 'gated') return;
    var gpaState = window.__gpaState || {};
    var frameId = gpaState.frameId | 0;
    var dcId = (gpaState.dcCount | 0);  // most-recent drawcall index
    var result = scan();
    if (result.truncated && depthCap > MIN_DEPTH) depthCap--;
    postSources(frameId, dcId, result);
  }

  function patchGL() {
    if (patched) return;
    var tracedMethods = [
      'uniform1f', 'uniform1i', 'uniform2f', 'uniform3f', 'uniform4f',
      'uniform1fv', 'uniform2fv', 'uniform3fv', 'uniform4fv',
      'uniformMatrix2fv', 'uniformMatrix3fv', 'uniformMatrix4fv',
      'bindTexture',
    ];
    function wrap(proto) {
      if (!proto) return;
      tracedMethods.forEach(function (m) {
        var orig = proto[m];
        if (!orig || orig.__gpaTraced) return;
        var wrapped = function () {
          var ret = orig.apply(this, arguments);
          try { onGatedCall(); } catch (_) { /* never let hooks throw */ }
          return ret;
        };
        wrapped.__gpaTraced = true;
        proto[m] = wrapped;
      });
    }
    if (typeof WebGLRenderingContext !== 'undefined') {
      wrap(WebGLRenderingContext.prototype);
    }
    if (typeof WebGL2RenderingContext !== 'undefined') {
      wrap(WebGL2RenderingContext.prototype);
    }
    patched = true;
  }

  // ---- SDK -----------------------------------------------------------
  function addDefaultRoots() {
    for (var i = 0; i < DEFAULT_ROOTS.length; i++) {
      var name = DEFAULT_ROOTS[i];
      var obj = window[name];
      if (obj && typeof obj === 'object') addRoot(obj, name);
    }
  }

  function addRoot(obj, name) {
    if (!obj || typeof obj !== 'object') return;
    name = name || ('root' + roots.length);
    for (var i = 0; i < roots.length; i++) {
      if (roots[i].obj === obj) { roots[i].name = name; return; }
    }
    roots.push({ obj: obj, name: name });
  }

  function readMode() {
    try {
      var m = window.localStorage && window.localStorage.GPA_TRACE_MODE;
      if (m === 'lazy' || m === 'gated' || m === 'eager') return m;
    } catch (_) { /* no localStorage */ }
    return 'gated';
  }

  function readEndpoint() {
    try {
      var e = window.localStorage && window.localStorage.GPA_TRACE_ENDPOINT;
      if (e) return e;
    } catch (_) { /* ignore */ }
    return DEFAULT_ENDPOINT;
  }

  function readToken() {
    try {
      var t = window.localStorage && window.localStorage.GPA_TRACE_TOKEN;
      if (t) return t;
    } catch (_) { /* ignore */ }
    return '';
  }

  function enable() {
    enabled = true;
    mode = readMode();
    endpoint = readEndpoint();
    authToken = readToken();
    depthCap = DEFAULT_DEPTH;
    addDefaultRoots();
    patchGL();
  }

  function disable() { enabled = false; }
  function isEnabled() { return enabled; }

  window.gpa = window.gpa || {};
  window.gpa.trace = {
    enable: enable,
    disable: disable,
    addRoot: addRoot,
    isEnabled: isEnabled,
    // Private-ish hooks for debugging / tests.
    _scan: scan,
    _hashValue: hashValue,
  };

  // If the page sets GPA_TRACE_MODE before load, auto-enable.
  try {
    if (window.localStorage && window.localStorage.GPA_TRACE_MODE) {
      enable();
    }
  } catch (_) { /* ignore */ }

  /* Example — manual smoke verification in a browser console:
   *
   *   window.gpa.trace.enable();
   *   window.myData = { zoom: 16.58, config: { threshold: 0.5 } };
   *   window.gpa.trace.addRoot(window.myData, 'myData');
   *   // Render a frame where the app calls gl.uniform1f(loc, 16.58).
   *   // Engine should receive POST /api/v1/frames/<N>/drawcalls/<M>/sources
   *   // with value_index containing a hash for 16.58 pointing at
   *   // "myData.zoom".
   */
})();
