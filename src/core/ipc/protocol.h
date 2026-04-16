#pragma once
#include <cstdint>

namespace gla::ipc {

// Current protocol version
static constexpr uint32_t PROTOCOL_VERSION = 1;

// Message format: [4-byte length (uint32_t, network byte order)] [1-byte type] [payload]
// The 'length' field counts the type byte + payload bytes.

enum class MsgType : uint8_t {
    MSG_HANDSHAKE      = 1,  // client → server: version, api_type, pid
    MSG_HANDSHAKE_OK   = 2,  // server → client: accepted
    MSG_HANDSHAKE_FAIL = 3,  // server → client: rejected (version mismatch)
    MSG_FRAME_READY    = 4,  // client → server: frame captured, slot index
    MSG_CONTROL        = 5,  // server → client: pause/resume/step
};

// Handshake payload (binary, packed)
struct HandshakePayload {
    uint32_t protocol_version;  // must equal PROTOCOL_VERSION
    uint32_t api_type;          // 0=GL, 1=VK, 2=WebGL
    uint32_t pid;
} __attribute__((packed));

// FrameReady payload
struct FrameReadyPayload {
    uint64_t frame_id;
    uint32_t shm_slot_index;
} __attribute__((packed));

// Control payload
struct ControlPayload {
    uint8_t  pause;        // 1 = pause
    uint8_t  resume;       // 1 = resume
    uint32_t step_frames;  // 0 = none
} __attribute__((packed));

} // namespace gla::ipc
