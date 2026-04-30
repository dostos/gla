// Path-1 demo — programmatic frame emit from Node + headless-gl.
//
// What this proves:
//   1. headless-gl creates a real GL context that the OpenGPA shim attaches
//      to under LD_PRELOAD (it dlopen()s libGL.so at runtime, so RTLD_NEXT
//      resolution works for our wrappers).
//   2. headless-gl never calls glXSwapBuffers, so the only existing
//      frame-emit path in the shim is dead. With the new exported
//      gpa_emit_frame() symbol, we can drive frame capture directly via
//      koffi (a Node FFI library — N-API based, no node-gyp build needed).
//
// Usage:
//   LD_PRELOAD=$SHIM_PATH \
//     GPA_SOCKET_PATH=/tmp/gpa_e2e.sock GPA_SHM_NAME=/gpa_e2e \
//     DISPLAY=:99 \
//     node demo.js [num_frames]
//
// On success the engine's frame count increments by num_frames (default 3).

const koffi = require('koffi');
const createGL = require('gl');

const NUM_FRAMES = parseInt(process.argv[2] || '3', 10);

// -- 1. Create an offscreen GL context --------------------------------------
const gl = createGL(64, 64, { preserveDrawingBuffer: true });
if (!gl) {
    console.error('headless-gl context creation failed (need Xvfb? try DISPLAY=:99)');
    process.exit(1);
}

// -- 2. Locate the OpenGPA GL shim ------------------------------------------
//    We deliberately do NOT dlopen by absolute path here: under LD_PRELOAD
//    the shim is already mapped into our process. Passing a soname-only
//    string to koffi.load() resolves against the already-loaded image,
//    matching the real-world deployment model. (If LD_PRELOAD wasn't set,
//    this would fail with ENOENT, which is the correct behavior.)
let shim;
try {
    shim = koffi.load('libgpa_gl.so');
} catch (e) {
    // Fallback: explicit GPA_SHIM_PATH env var, useful for ad-hoc testing
    // outside of LD_PRELOAD (won't actually capture frames, but lets us
    // surface obvious dlopen errors).
    const fallback = process.env.GPA_SHIM_PATH;
    if (!fallback) {
        console.error('koffi.load("libgpa_gl.so") failed; set LD_PRELOAD '
                    + 'or GPA_SHIM_PATH. Underlying error:', e.message);
        process.exit(1);
    }
    shim = koffi.load(fallback);
}

const gpa_emit_frame = shim.func('void gpa_emit_frame()');

// -- 3. Render and emit frames ----------------------------------------------
//    Per-frame: clear to a different colour, do a tiny draw, then trigger
//    capture. The clear colour cycles so a human looking at the captured
//    framebuffer can tell frames apart.
const colours = [
    [1.0, 0.2, 0.2, 1.0],   // red
    [0.2, 1.0, 0.2, 1.0],   // green
    [0.2, 0.2, 1.0, 1.0],   // blue
    [1.0, 1.0, 0.2, 1.0],   // yellow
    [1.0, 0.2, 1.0, 1.0],   // magenta
];

// Build the simplest possible draw call: a single triangle via
// glDrawArrays. We need an array buffer + a trivial shader for the GL
// state to be non-trivially recordable by the shim.
const vsSrc = '#version 100\nattribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }';
const fsSrc = '#version 100\nprecision mediump float; void main(){ gl_FragColor = vec4(1.0); }';

const vs = gl.createShader(gl.VERTEX_SHADER);
gl.shaderSource(vs, vsSrc); gl.compileShader(vs);
const fs = gl.createShader(gl.FRAGMENT_SHADER);
gl.shaderSource(fs, fsSrc); gl.compileShader(fs);
const prog = gl.createProgram();
gl.attachShader(prog, vs); gl.attachShader(prog, fs);
gl.bindAttribLocation(prog, 0, 'p');
gl.linkProgram(prog);
gl.useProgram(prog);

const buf = gl.createBuffer();
gl.bindBuffer(gl.ARRAY_BUFFER, buf);
gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
    -0.5, -0.5,
     0.5, -0.5,
     0.0,  0.5,
]), gl.STATIC_DRAW);
gl.enableVertexAttribArray(0);
gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

console.log(`[demo] rendering and emitting ${NUM_FRAMES} frame(s)…`);
for (let i = 0; i < NUM_FRAMES; i++) {
    const c = colours[i % colours.length];
    gl.clearColor(c[0], c[1], c[2], c[3]);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.finish();
    gpa_emit_frame();
    console.log(`[demo]   frame ${i+1}/${NUM_FRAMES}: cleared to (${c.slice(0,3).join(', ')}) + 1 triangle`);
}

console.log('[demo] done.');
