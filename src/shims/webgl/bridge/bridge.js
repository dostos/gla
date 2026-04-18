'use strict';

const WebSocket = require('ws');
const net = require('net');
const { Buffer } = require('buffer');

const WS_PORT = parseInt(process.env.GLA_WS_PORT || '18081', 10);
const GLA_SOCKET = process.env.GLA_SOCKET_PATH || '/tmp/gla.sock';

// ---------------------------------------------------------------------------
// Protocol constants (must match engine's ipc_client.h)
// ---------------------------------------------------------------------------
const MSG_HANDSHAKE   = 1;
const MSG_FRAME_READY = 4;
const API_TYPE_WEBGL  = 2;
const PROTOCOL_VER    = 1;

class GlaBridge {
  constructor() {
    this.wsServer = null;
    this.engineSocket = null;
    this.connected = false;
    this.reconnectTimer = null;
  }

  // -------------------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------------------
  start() {
    this.connectToEngine();

    this.wsServer = new WebSocket.Server({ port: WS_PORT, host: '127.0.0.1' });
    this.wsServer.on('connection', (ws) => this.handleClient(ws));
    this.wsServer.on('error', (err) => {
      console.error('[bridge] WebSocket server error:', err.message);
    });

    console.log(`[bridge] Listening on ws://127.0.0.1:${WS_PORT}`);
    console.log(`[bridge] Engine socket: ${GLA_SOCKET}`);
  }

  // -------------------------------------------------------------------------
  // Engine connection (Unix domain socket)
  // -------------------------------------------------------------------------
  connectToEngine() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    this.engineSocket = net.createConnection(GLA_SOCKET);

    this.engineSocket.on('connect', () => {
      this.connected = true;
      console.log('[bridge] Connected to OpenGPA engine');
      this.sendHandshake();
    });

    this.engineSocket.on('error', (err) => {
      console.error('[bridge] Engine connection error:', err.message);
      this.connected = false;
      this.scheduleReconnect();
    });

    this.engineSocket.on('close', () => {
      if (this.connected) {
        console.log('[bridge] Engine socket closed');
      }
      this.connected = false;
      this.scheduleReconnect();
    });

    // Consume any inbound data from the engine (ACKs, etc.) to avoid backpressure.
    this.engineSocket.on('data', (data) => {
      // TODO: parse engine responses (e.g. readback requests) when needed.
      void data;
    });
  }

  scheduleReconnect() {
    if (!this.reconnectTimer) {
      this.reconnectTimer = setTimeout(() => {
        console.log('[bridge] Retrying engine connection...');
        this.connectToEngine();
      }, 3000);
    }
  }

  // -------------------------------------------------------------------------
  // Binary message helpers
  // Protocol: [4-byte length BE (= 1 + payload_len)][1-byte type][payload]
  // -------------------------------------------------------------------------
  buildMessage(type, payload) {
    const totalLen = 1 + payload.length;   // type byte + payload
    const header = Buffer.alloc(4);
    header.writeUInt32BE(totalLen, 0);
    return Buffer.concat([header, Buffer.from([type]), payload]);
  }

  sendHandshake() {
    // Payload: protocol_version(4) | api_type(4) | pid(4)
    const payload = Buffer.alloc(12);
    payload.writeUInt32BE(PROTOCOL_VER,    0);
    payload.writeUInt32BE(API_TYPE_WEBGL,  4);
    payload.writeUInt32BE(process.pid,     8);
    this.engineSocket.write(this.buildMessage(MSG_HANDSHAKE, payload));
    console.log('[bridge] Sent HANDSHAKE (api_type=WebGL, pid=' + process.pid + ')');
  }

  sendFrameReady(frameId, drawCallCount) {
    // Payload: frame_id(4) | draw_call_count(4)
    // v1: no SHM — metadata only. Full pixel readback deferred to a future
    //     milestone that adds a native addon for shared memory access.
    const payload = Buffer.alloc(8);
    payload.writeUInt32BE(frameId,        0);
    payload.writeUInt32BE(drawCallCount,  4);
    this.engineSocket.write(this.buildMessage(MSG_FRAME_READY, payload));
  }

  // -------------------------------------------------------------------------
  // WebSocket client handler (one connection per browser tab / page)
  // -------------------------------------------------------------------------
  handleClient(ws) {
    console.log('[bridge] WebGL client connected');

    ws.on('message', (data) => {
      try {
        const msg = JSON.parse(data);
        switch (msg.type) {
          case 'frame':
            this.handleFrame(msg);
            break;
          default:
            console.warn('[bridge] Unknown message type:', msg.type);
        }
      } catch (e) {
        console.error('[bridge] Parse error:', e.message);
      }
    });

    ws.on('close', () => {
      console.log('[bridge] WebGL client disconnected');
    });

    ws.on('error', (err) => {
      console.error('[bridge] Client socket error:', err.message);
    });
  }

  // -------------------------------------------------------------------------
  // Frame processing
  // -------------------------------------------------------------------------
  handleFrame(frameData) {
    const drawCallCount = Array.isArray(frameData.drawCalls)
      ? frameData.drawCalls.length
      : 0;

    console.log(
      `[bridge] Frame ${frameData.frameId}: ${drawCallCount} draw call(s)` +
      (frameData.viewport ? ` viewport=${JSON.stringify(frameData.viewport)}` : '')
    );

    if (!this.connected) {
      // Engine not available — log only (passthrough mode).
      return;
    }

    this.sendFrameReady(frameData.frameId, drawCallCount);

    // TODO (M6+): For full integration, serialize draw call metadata into SHM.
    //   That requires either:
    //     a) a native Node.js addon (node-addon-api) that calls shm_open/mmap, or
    //     b) passing the JSON blob inline in a variable-length socket message.
    //   For v1, the engine receives only frame_id + draw_call_count.
  }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
const bridge = new GlaBridge();
bridge.start();
