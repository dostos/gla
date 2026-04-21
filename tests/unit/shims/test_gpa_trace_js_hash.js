// Canonical-hash parity test for the JS side of `gpa trace`.
//
// Loads src/shims/webgl/extension/gpa-trace.js into a minimal DOM-less
// sandbox + asserts that its `_hashValue()` emits the same canonical
// numeric format as the C shim (`native_trace.c::number_to_js_base36`)
// and the Python parser (`routes_trace.py::_parse_canonical_number`).
//
// The expected strings below were hand-computed from the spec and
// cross-verified against the Python reference in
// `tests/unit/python/test_trace_hash_parity.py::canonical_py`. They are
// the authoritative wire-format contract for numbers.
//
// Run:
//   node tests/unit/shims/test_gpa_trace_js_hash.js
//
// Integrated into the Python test suite as a skipped-if-no-node parity
// test in test_trace_hash_parity.py.

'use strict';

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

const EXT_PATH = path.resolve(
  __dirname, '..', '..', '..',
  'src', 'shims', 'webgl', 'extension', 'gpa-trace.js');

// ---- minimal browser-ish sandbox -------------------------------------
const sandbox = {
  window: {},
  // IIFEs in gpa-trace.js probe `typeof Node` etc; a blank object is enough.
  Node: undefined,
  WeakSet: WeakSet,
  ArrayBuffer: ArrayBuffer,
  Float64Array: Float64Array,
  Uint8Array: Uint8Array,
  DataView: DataView,
  WebGLRenderingContext: undefined,
  WebGL2RenderingContext: undefined,
  // performance is optional (falls back to Date.now).
  performance: { now: () => Date.now() },
  console: console,
  // fetch is referenced in postSources but only inside the async branch
  // — scan/hashValue never touch it. Provide a stub anyway.
  fetch: () => ({ catch: () => {} }),
};
sandbox.window.localStorage = undefined;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

const src = fs.readFileSync(EXT_PATH, 'utf-8');
vm.runInContext(src, sandbox, { filename: 'gpa-trace.js' });

const trace = sandbox.window.gpa && sandbox.window.gpa.trace;
if (!trace || typeof trace._hashValue !== 'function') {
  console.error('FAIL: window.gpa.trace._hashValue not exposed by extension');
  process.exit(2);
}

// ---- expected canonical strings --------------------------------------
// Format: hashValue() returns `n:` + canonicalNumber(v) for numbers.
// canonicalNumber() spec (must match C + Python):
//   NaN           -> "NaN"
//   +Infinity     -> "Inf"
//   -Infinity     -> "-Inf"
//   0 / -0        -> "0"
//   |v|<2^53 int  -> signed decimal
//   other finite  -> "f:" + 16 hex chars of IEEE-754 big-endian bits
const CASES = [
  { v: 0.0,                 expected: 'n:0'                },
  { v: -0.0,                expected: 'n:0'                },
  { v: 1.0,                 expected: 'n:1'                },
  { v: -1.0,                expected: 'n:-1'               },
  { v: 42.0,                expected: 'n:42'               },
  { v: -42.0,               expected: 'n:-42'              },
  { v: 100.0,               expected: 'n:100'              },
  { v: 16.58,               expected: 'n:f:4030947ae147ae14' },
  { v: 3.14159,             expected: 'n:f:400921f9f01b866e' },
  { v: NaN,                 expected: 'n:NaN'              },
  { v: Infinity,            expected: 'n:Inf'              },
  { v: -Infinity,           expected: 'n:-Inf'             },
];

let fail = 0;
for (const c of CASES) {
  const got = trace._hashValue(c.v);
  try {
    assert.strictEqual(got, c.expected,
      `v=${c.v} expected=${c.expected} got=${got}`);
    console.log(`PASS ${JSON.stringify(c.v)} -> ${got}`);
  } catch (e) {
    console.error(`FAIL ${e.message}`);
    fail++;
  }
}

if (fail) {
  console.error(`\n${fail}/${CASES.length} case(s) failed`);
  process.exit(1);
}
console.log(`\nAll ${CASES.length} JS canonical-hash parity cases pass.`);
