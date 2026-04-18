(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // State tracking — mirrors the shadow state kept by the OpenGL LD_PRELOAD shim
  // ---------------------------------------------------------------------------
  const state = {
    connected: false,
    ws: null,
    frameNumber: 0,
    drawCalls: [],
    currentProgram: null,
    boundTextures: {},   // target -> texture object
    viewport: [0, 0, 0, 0],
    boundFramebuffer: null,
    activeTexture: 0,
    blendFunc: [0, 0],
    depthFunc: 0,
    cullFace: 0,
    frontFace: 0,
    scissor: [0, 0, 0, 0],
    enabledCaps: {},
  };

  // ---------------------------------------------------------------------------
  // WebSocket connection to the Node.js bridge
  // ---------------------------------------------------------------------------
  function connect() {
    try {
      state.ws = new WebSocket('ws://127.0.0.1:18081');
      state.ws.onopen = function () {
        state.connected = true;
        console.log('[OpenGPA] Connected to bridge');
      };
      state.ws.onclose = function () {
        state.connected = false;
        console.log('[OpenGPA] Disconnected from bridge');
        // Attempt reconnect after 3 s so short bridge restarts are tolerated.
        setTimeout(connect, 3000);
      };
      state.ws.onerror = function () {
        // Silently swallow — bridge may simply not be running (passthrough mode).
      };
    } catch (e) {
      // Bridge not running — passthrough mode, no interception overhead.
    }
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------
  function sendFrameData() {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    const frameData = {
      type: 'frame',
      frameId: state.frameNumber,
      drawCalls: state.drawCalls,
      viewport: state.viewport,
      // Framebuffer readback (gl.readPixels) is expensive — deferred to on-demand
      // requests from the bridge rather than sent every frame.
    };
    state.ws.send(JSON.stringify(frameData));
  }

  function recordDrawCall(gl, mode, vertexCount, indexCount, instanceCount) {
    state.drawCalls.push({
      id: state.drawCalls.length,
      primitive: mode,
      vertexCount: vertexCount,
      indexCount: indexCount,
      instanceCount: instanceCount,
      program: state.currentProgram,
      viewport: state.viewport.slice(),
      textures: Object.assign({}, state.boundTextures),
      boundFramebuffer: state.boundFramebuffer,
    });
  }

  // ---------------------------------------------------------------------------
  // Monkey-patch a WebGL context prototype
  // ---------------------------------------------------------------------------
  function patchContext(proto, name) {

    // -- Draw calls ----------------------------------------------------------
    const origDrawArrays = proto.drawArrays;
    proto.drawArrays = function (mode, first, count) {
      recordDrawCall(this, mode, count, 0, 1);
      return origDrawArrays.call(this, mode, first, count);
    };

    const origDrawElements = proto.drawElements;
    proto.drawElements = function (mode, count, type, offset) {
      recordDrawCall(this, mode, 0, count, 1);
      return origDrawElements.call(this, mode, count, type, offset);
    };

    const origDrawArraysInstanced = proto.drawArraysInstanced;
    if (origDrawArraysInstanced) {
      proto.drawArraysInstanced = function (mode, first, count, instanceCount) {
        recordDrawCall(this, mode, count, 0, instanceCount);
        return origDrawArraysInstanced.call(this, mode, first, count, instanceCount);
      };
    }

    const origDrawElementsInstanced = proto.drawElementsInstanced;
    if (origDrawElementsInstanced) {
      proto.drawElementsInstanced = function (mode, count, type, offset, instanceCount) {
        recordDrawCall(this, mode, 0, count, instanceCount);
        return origDrawElementsInstanced.call(this, mode, count, type, offset, instanceCount);
      };
    }

    // -- Program -------------------------------------------------------------
    const origUseProgram = proto.useProgram;
    proto.useProgram = function (program) {
      state.currentProgram = program;
      return origUseProgram.call(this, program);
    };

    // -- Textures ------------------------------------------------------------
    const origBindTexture = proto.bindTexture;
    proto.bindTexture = function (target, texture) {
      state.boundTextures[target] = texture;
      return origBindTexture.call(this, target, texture);
    };

    const origActiveTexture = proto.activeTexture;
    proto.activeTexture = function (texture) {
      state.activeTexture = texture;
      return origActiveTexture.call(this, texture);
    };

    // -- Viewport / scissor --------------------------------------------------
    const origViewport = proto.viewport;
    proto.viewport = function (x, y, w, h) {
      state.viewport = [x, y, w, h];
      return origViewport.call(this, x, y, w, h);
    };

    const origScissor = proto.scissor;
    proto.scissor = function (x, y, w, h) {
      state.scissor = [x, y, w, h];
      return origScissor.call(this, x, y, w, h);
    };

    // -- Framebuffer ---------------------------------------------------------
    const origBindFramebuffer = proto.bindFramebuffer;
    proto.bindFramebuffer = function (target, framebuffer) {
      state.boundFramebuffer = framebuffer;
      return origBindFramebuffer.call(this, target, framebuffer);
    };

    // -- Capability toggles --------------------------------------------------
    const origEnable = proto.enable;
    proto.enable = function (cap) {
      state.enabledCaps[cap] = true;
      return origEnable.call(this, cap);
    };

    const origDisable = proto.disable;
    proto.disable = function (cap) {
      state.enabledCaps[cap] = false;
      return origDisable.call(this, cap);
    };

    // -- Blend / depth / cull / front face -----------------------------------
    const origBlendFunc = proto.blendFunc;
    proto.blendFunc = function (sfactor, dfactor) {
      state.blendFunc = [sfactor, dfactor];
      return origBlendFunc.call(this, sfactor, dfactor);
    };

    const origDepthFunc = proto.depthFunc;
    proto.depthFunc = function (func) {
      state.depthFunc = func;
      return origDepthFunc.call(this, func);
    };

    const origCullFace = proto.cullFace;
    proto.cullFace = function (mode) {
      state.cullFace = mode;
      return origCullFace.call(this, mode);
    };

    const origFrontFace = proto.frontFace;
    proto.frontFace = function (mode) {
      state.frontFace = mode;
      return origFrontFace.call(this, mode);
    };

    // -- Uniform setters (track but do not record per-call to keep overhead low)
    // Intercept uniform1i/uniform1f/uniformMatrix4fv as representative examples.
    ['uniform1i', 'uniform1f', 'uniform2f', 'uniform3f', 'uniform4f',
     'uniform1iv', 'uniform1fv', 'uniform2fv', 'uniform3fv', 'uniform4fv',
     'uniformMatrix2fv', 'uniformMatrix3fv', 'uniformMatrix4fv'].forEach(function (uname) {
      const orig = proto[uname];
      if (!orig) return;
      proto[uname] = function () {
        return orig.apply(this, arguments);
      };
    });

    console.log('[OpenGPA] Patched ' + name + ' prototype');
  }

  // ---------------------------------------------------------------------------
  // Frame boundary — hook requestAnimationFrame
  // ---------------------------------------------------------------------------
  const origRAF = window.requestAnimationFrame;
  window.requestAnimationFrame = function (callback) {
    return origRAF.call(window, function (timestamp) {
      // Flush accumulated draw calls for the frame that is about to be presented.
      if (state.connected && state.drawCalls.length > 0) {
        sendFrameData();
      }
      // Reset per-frame state.
      state.drawCalls = [];
      state.frameNumber++;
      callback(timestamp);
    });
  };

  // ---------------------------------------------------------------------------
  // Patch WebGL1 and WebGL2 context prototypes
  // ---------------------------------------------------------------------------
  if (window.WebGLRenderingContext) {
    patchContext(WebGLRenderingContext.prototype, 'WebGL');
  }
  if (window.WebGL2RenderingContext) {
    patchContext(WebGL2RenderingContext.prototype, 'WebGL2');
  }

  // ---------------------------------------------------------------------------
  // Auto-connect to bridge
  // ---------------------------------------------------------------------------
  connect();

})();
