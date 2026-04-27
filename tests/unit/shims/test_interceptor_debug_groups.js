// Debug-marker capture parity test for the WebGL interceptor.
//
// Loads src/shims/webgl/extension/interceptor.js into a minimal DOM-less
// sandbox with a stubbed WebGL2 context prototype + a stubbed WebSocket.
// Drives push/pop/draw sequences and asserts that the JSON payload sent
// over WebSocket attaches `debug_groups` per drawcall and surfaces
// `debugGroupErrors` per frame.
//
// The acceptance criteria mirrored here come from the spec for the
// Tier-3 `gpa scene-find` link primitive (see
// `src/python/gpa/framework/threejs_link_plugin.js` and the
// `NormalizedDrawCall::debug_groups` C++ field).
//
// Run:
//   node tests/unit/shims/test_interceptor_debug_groups.js
//
// Wired into the Python test suite via test_interceptor_debug_groups.py
// as a skipped-if-no-node parity test.

'use strict';

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

const EXT_PATH = path.resolve(
  __dirname, '..', '..', '..',
  'src', 'shims', 'webgl', 'extension', 'interceptor.js');

// ---------------------------------------------------------------------
// Test harness — runs `interceptor.js` against a fresh stub each time.
// ---------------------------------------------------------------------

function makeSandbox() {
  // Stubbed WebGL2 prototype with the methods the interceptor patches.
  // The interceptor MUTATES the prototype (monkey-patches), so each test
  // builds its own isolated prototype object inside its own VM context.
  function noop() {}

  const proto2 = {
    drawArrays: noop,
    drawElements: noop,
    drawArraysInstanced: noop,
    drawElementsInstanced: noop,
    useProgram: noop,
    bindTexture: noop,
    activeTexture: noop,
    viewport: noop,
    scissor: noop,
    bindFramebuffer: noop,
    enable: noop,
    disable: noop,
    blendFunc: noop,
    depthFunc: noop,
    cullFace: noop,
    frontFace: noop,
    pushDebugGroup: noop,   // WebGL2 native
    popDebugGroup: noop,
    getExtension: function (_n) { return null; },
  };
  function WebGL2RenderingContext() {}
  WebGL2RenderingContext.prototype = proto2;

  // WebGL1 stub: no native pushDebugGroup, but EXT_debug_marker available.
  const proto1 = {
    drawArrays: noop,
    drawElements: noop,
    useProgram: noop,
    bindTexture: noop,
    activeTexture: noop,
    viewport: noop,
    scissor: noop,
    bindFramebuffer: noop,
    enable: noop,
    disable: noop,
    blendFunc: noop,
    depthFunc: noop,
    cullFace: noop,
    frontFace: noop,
    // pushDebugGroup / popDebugGroup intentionally absent.
    getExtension: function (name) {
      if (name === 'EXT_debug_marker') {
        return {
          pushGroupMarkerEXT: function () {},
          popGroupMarkerEXT: function () {},
        };
      }
      return null;
    },
  };
  function WebGLRenderingContext() {}
  WebGLRenderingContext.prototype = proto1;

  // Capture WebSocket sends so the test can inspect frame payloads.
  const sentFrames = [];
  function FakeWebSocket(_url) {
    this.readyState = FakeWebSocket.OPEN;
    // Trigger onopen synchronously after caller assigns it. The interceptor
    // sets onopen *after* construction, so we defer with setTimeout(0).
    const self = this;
    setTimeout(function () {
      if (typeof self.onopen === 'function') self.onopen();
    }, 0);
  }
  FakeWebSocket.OPEN = 1;
  FakeWebSocket.prototype.send = function (msg) {
    sentFrames.push(JSON.parse(msg));
  };

  // Minimal RAF stub — fires the callback immediately so the per-frame
  // boundary executes synchronously inside the test driver.
  let rafQueue = [];
  function requestAnimationFrame(cb) {
    rafQueue.push(cb);
    return rafQueue.length;
  }
  function flushRAF() {
    const q = rafQueue;
    rafQueue = [];
    for (const cb of q) cb(performance.now());
  }

  const sandbox = {
    window: {},
    WebGLRenderingContext,
    WebGL2RenderingContext,
    WebSocket: FakeWebSocket,
    setTimeout,
    console,
    performance: { now: () => Date.now() },
  };
  sandbox.window.WebGLRenderingContext = WebGLRenderingContext;
  sandbox.window.WebGL2RenderingContext = WebGL2RenderingContext;
  sandbox.window.requestAnimationFrame = requestAnimationFrame;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);

  const src = fs.readFileSync(EXT_PATH, 'utf-8');
  vm.runInContext(src, sandbox, { filename: 'interceptor.js' });

  // The interceptor wrapped window.requestAnimationFrame — pull the wrapped
  // version so the driver schedules through it (which is what triggers the
  // per-frame send + state reset).
  const wrappedRAF = sandbox.window.requestAnimationFrame;

  return {
    sandbox,
    proto1,
    proto2,
    sentFrames,
    flushRAF,
    raf: wrappedRAF,
  };
}

// Wait briefly so FakeWebSocket.onopen fires (queued via setTimeout(0)).
function settleOpen(cb) { setTimeout(cb, 5); }

// Build a stub gl context. Calls flow through proto via `this`.
function makeContext(proto) {
  const gl = Object.create(proto);
  return gl;
}

// ---------------------------------------------------------------------
// Test cases — one per acceptance criterion.
// ---------------------------------------------------------------------

const TESTS = [];
function test(name, fn) { TESTS.push({ name, fn }); }

test('empty stack — drawcall outside any group has debug_groups: []',
  function (done) {
    const h = makeSandbox();
    const gl = makeContext(h.proto2);
    settleOpen(function () {
      h.raf(function () {
        gl.drawArrays(4, 0, 3);
      });
      h.flushRAF();
      // The first RAF tick *flushes* prior-frame drawcalls (none) then runs
      // the callback that issues the draw. We need a second RAF to flush.
      h.raf(function () {});
      h.flushRAF();
      assert.strictEqual(h.sentFrames.length, 1,
        'expected exactly one frame payload');
      const dc = h.sentFrames[0].drawCalls[0];
      assert.deepStrictEqual(dc.debug_groups, [],
        'drawcall outside any group must carry debug_groups: []');
      assert.strictEqual(h.sentFrames[0].debugGroupErrors, 0);
      done();
    });
  });

test('single push+pop — drawcall inside group has debug_groups: ["Helmet"]',
  function (done) {
    const h = makeSandbox();
    const gl = makeContext(h.proto2);
    settleOpen(function () {
      h.raf(function () {
        gl.pushDebugGroup(0x824b, 0, 'Helmet');
        gl.drawArrays(4, 0, 3);
        gl.popDebugGroup();
      });
      h.flushRAF();
      h.raf(function () {});
      h.flushRAF();
      assert.strictEqual(h.sentFrames.length, 1);
      const dc = h.sentFrames[0].drawCalls[0];
      assert.deepStrictEqual(dc.debug_groups, ['Helmet']);
      done();
    });
  });

test('nested push+pop — debug_groups: ["Scene", "Helmet"]',
  function (done) {
    const h = makeSandbox();
    const gl = makeContext(h.proto2);
    settleOpen(function () {
      h.raf(function () {
        gl.pushDebugGroup(0x824b, 0, 'Scene');
        gl.pushDebugGroup(0x824b, 0, 'Helmet');
        gl.drawArrays(4, 0, 3);
        gl.popDebugGroup();
        gl.popDebugGroup();
      });
      h.flushRAF();
      h.raf(function () {});
      h.flushRAF();
      const dc = h.sentFrames[0].drawCalls[0];
      assert.deepStrictEqual(dc.debug_groups, ['Scene', 'Helmet']);
      done();
    });
  });

test('drawcall after popDebugGroup — debug_groups reverts to outer group',
  function (done) {
    const h = makeSandbox();
    const gl = makeContext(h.proto2);
    settleOpen(function () {
      h.raf(function () {
        gl.pushDebugGroup(0x824b, 0, 'Scene');
        gl.pushDebugGroup(0x824b, 0, 'Helmet');
        gl.drawArrays(4, 0, 3);   // [Scene, Helmet]
        gl.popDebugGroup();
        gl.drawArrays(4, 0, 3);   // [Scene]
        gl.popDebugGroup();
        gl.drawArrays(4, 0, 3);   // []
      });
      h.flushRAF();
      h.raf(function () {});
      h.flushRAF();
      const dcs = h.sentFrames[0].drawCalls;
      assert.deepStrictEqual(dcs[0].debug_groups, ['Scene', 'Helmet']);
      assert.deepStrictEqual(dcs[1].debug_groups, ['Scene']);
      assert.deepStrictEqual(dcs[2].debug_groups, []);
      // Also confirm slice() was used (no aliasing): mutating one snapshot
      // must not propagate to siblings.
      dcs[0].debug_groups.push('LEAK');
      assert.deepStrictEqual(dcs[1].debug_groups, ['Scene'],
        'debug_groups must be independent snapshots, not aliased');
      done();
    });
  });

test('popDebugGroup on empty stack — increments debugGroupErrors',
  function (done) {
    const h = makeSandbox();
    const gl = makeContext(h.proto2);
    settleOpen(function () {
      h.raf(function () {
        gl.popDebugGroup();        // empty -> error 1
        gl.popDebugGroup();        // empty -> error 2
        gl.drawArrays(4, 0, 3);
      });
      h.flushRAF();
      h.raf(function () {});
      h.flushRAF();
      const f = h.sentFrames[0];
      assert.strictEqual(f.debugGroupErrors, 2,
        'two stray pops must yield debugGroupErrors === 2');
      assert.deepStrictEqual(f.drawCalls[0].debug_groups, []);
      done();
    });
  });

test('WebGL1 with EXT_debug_marker — pushGroupMarkerEXT records group',
  function (done) {
    const h = makeSandbox();
    const gl = makeContext(h.proto1);
    settleOpen(function () {
      h.raf(function () {
        // Acquire EXT_debug_marker (the interceptor wraps the returned ext).
        const ext = gl.getExtension('EXT_debug_marker');
        assert.ok(ext, 'EXT_debug_marker stub must be returned');
        ext.pushGroupMarkerEXT('Helmet');
        gl.drawArrays(4, 0, 3);
        ext.popGroupMarkerEXT();
        gl.drawArrays(4, 0, 3);
      });
      h.flushRAF();
      h.raf(function () {});
      h.flushRAF();
      const dcs = h.sentFrames[0].drawCalls;
      assert.deepStrictEqual(dcs[0].debug_groups, ['Helmet'],
        'WebGL1 + EXT_debug_marker must populate debug_groups');
      assert.deepStrictEqual(dcs[1].debug_groups, []);
      done();
    });
  });

test('WebGL1 without EXT_debug_marker — does not throw, debug_groups: []',
  function (done) {
    // Build a sandbox where getExtension returns null for everything.
    const h = makeSandbox();
    // Override AFTER patching by the interceptor — point getExtension at
    // a dud. The interceptor's wrapper will still call origGetExtension
    // which is the original null-returning stub on proto1, so we need to
    // invoke through a fresh proto1-derived gl that the interceptor has
    // already patched.
    const gl = makeContext(h.proto1);
    settleOpen(function () {
      // Force getExtension to return null (no EXT_debug_marker on this UA).
      // The interceptor's getExtension wrapper handles this gracefully.
      gl.getExtension = function () { return null; };
      h.raf(function () {
        const ext = gl.getExtension('EXT_debug_marker');
        assert.strictEqual(ext, null);
        // No native pushDebugGroup on WebGL1 either — must not throw.
        assert.strictEqual(typeof gl.pushDebugGroup, 'undefined');
        gl.drawArrays(4, 0, 3);
      });
      h.flushRAF();
      h.raf(function () {});
      h.flushRAF();
      const dc = h.sentFrames[0].drawCalls[0];
      assert.deepStrictEqual(dc.debug_groups, []);
      assert.strictEqual(h.sentFrames[0].debugGroupErrors, 0);
      done();
    });
  });

test('debugGroupErrors resets after each frame send',
  function (done) {
    const h = makeSandbox();
    const gl = makeContext(h.proto2);
    settleOpen(function () {
      h.raf(function () {
        gl.popDebugGroup();
        gl.drawArrays(4, 0, 3);
      });
      h.flushRAF();
      h.raf(function () {});  // flush frame 1
      h.flushRAF();
      h.raf(function () {
        gl.drawArrays(4, 0, 3);
      });
      h.flushRAF();
      h.raf(function () {});  // flush frame 2
      h.flushRAF();
      assert.strictEqual(h.sentFrames.length, 2);
      assert.strictEqual(h.sentFrames[0].debugGroupErrors, 1);
      assert.strictEqual(h.sentFrames[1].debugGroupErrors, 0,
        'error counter must reset between frames');
      done();
    });
  });

// ---------------------------------------------------------------------
// Driver — runs cases serially because each test waits for the
// FakeWebSocket onopen tick (queued setTimeout). Sync-style with done()
// callbacks keeps the harness portable to plain node.
// ---------------------------------------------------------------------

let idx = 0;
let fail = 0;
function runNext() {
  if (idx >= TESTS.length) {
    if (fail) {
      console.error('\n' + fail + '/' + TESTS.length + ' case(s) failed');
      process.exit(1);
    }
    console.log('\nAll ' + TESTS.length + ' interceptor debug-group cases pass.');
    process.exit(0);
  }
  const t = TESTS[idx++];
  try {
    t.fn(function () {
      console.log('PASS ' + t.name);
      runNext();
    });
  } catch (e) {
    console.error('FAIL ' + t.name + ': ' + (e && e.stack || e));
    fail++;
    runNext();
  }
}
runNext();
