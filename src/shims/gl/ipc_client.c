#define _GNU_SOURCE
#include "ipc_client.h"

#include <errno.h>
#include <fcntl.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <arpa/inet.h>

/* --------------------------------------------------------------------------
 * Mirror of shm_ring_buffer.h layout (must stay in sync)
 * -------------------------------------------------------------------------- */

/* Slot state values matching SlotState enum in shm_ring_buffer.h */
#define SLOT_FREE    0u
#define SLOT_WRITING 1u
#define SLOT_READY   2u
#define SLOT_READING 3u

/* RingHeader — placed at byte 0 of the shm segment */
typedef struct {
    uint64_t magic;       /* GLA_SHM_MAGIC = 0x474C415F53484D00 */
    uint32_t num_slots;
    uint32_t _pad;
    uint64_t slot_size;   /* usable data bytes per slot */
    uint64_t total_size;  /* total mmap size (informational) */
} RingHeader;

#define GLA_SHM_MAGIC 0x474C415F53484D00ULL

/* SlotHeader — 64 bytes, cache-line aligned, placed before each data region.
 * Layout (matches C++ definition):
 *   [0]  state     atomic uint32  4 bytes
 *   [4]  _pad0     uint32         4 bytes
 *   [8]  frame_id  uint64         8 bytes
 *   [16] data_size uint64         8 bytes
 *   [24] _pad1     uint8[40]     40 bytes
 *                               = 64 bytes
 */
typedef struct {
    _Atomic uint32_t state;
    uint32_t         _pad0;
    uint64_t         frame_id;
    uint64_t         data_size;
    uint8_t          _pad1[40];
} SlotHeader;

_Static_assert(sizeof(SlotHeader) == 64, "SlotHeader must be exactly 64 bytes");

/* --------------------------------------------------------------------------
 * Wire protocol (mirrors protocol.h — pure C, no namespaces)
 * -------------------------------------------------------------------------- */

/* Message framing: [uint32_t length (BE)][uint8_t type][payload] */
/* length = 1 (type byte) + sizeof(payload) */

#define MSG_HANDSHAKE      1u
#define MSG_HANDSHAKE_OK   2u
#define MSG_HANDSHAKE_FAIL 3u
#define MSG_FRAME_READY    4u
#define MSG_CONTROL        5u

#define PROTOCOL_VERSION 1u
#define API_TYPE_GL      0u

typedef struct __attribute__((packed)) {
    uint32_t protocol_version;
    uint32_t api_type;
    uint32_t pid;
} HandshakePayload;

typedef struct __attribute__((packed)) {
    uint64_t frame_id;
    uint32_t shm_slot_index;
} FrameReadyPayload;

typedef struct __attribute__((packed)) {
    uint8_t  pause;
    uint8_t  resume;
    uint32_t step_frames;
} ControlPayload;

/* --------------------------------------------------------------------------
 * Module state
 * -------------------------------------------------------------------------- */

static int   g_sock_fd    = -1;
static void* g_shm_base   = NULL;
static size_t g_shm_size  = 0;
static uint32_t g_num_slots = 0;
static uint64_t g_slot_size = 0;
static uint32_t g_next_write = 0;   /* round-robin hint */

/* --------------------------------------------------------------------------
 * Internal helpers
 * -------------------------------------------------------------------------- */

static SlotHeader* slot_header(uint32_t index) {
    /* Layout: RingHeader (32 bytes, but slots start at offset aligned to 64).
     * The C++ code places slot headers right after the RingHeader with natural
     * alignment. sizeof(RingHeader) = 32 bytes; next 64-byte boundary = 64. */
    uint8_t* base = (uint8_t*)g_shm_base;
    /* Slot region starts at offset 64 (first 64-byte-aligned boundary after
     * the 32-byte RingHeader). Each slot occupies 64 (header) + slot_size. */
    size_t slot_stride = (size_t)(64 + g_slot_size);
    return (SlotHeader*)(base + 64 + index * slot_stride);
}

static void* slot_data(uint32_t index) {
    return (uint8_t*)slot_header(index) + 64;
}

/* Send exactly 'len' bytes; returns 0 on success, -1 on error */
static int send_all(int fd, const void* buf, size_t len) {
    const uint8_t* p = (const uint8_t*)buf;
    while (len > 0) {
        ssize_t n = send(fd, p, len, MSG_NOSIGNAL);
        if (n <= 0) return -1;
        p   += n;
        len -= (size_t)n;
    }
    return 0;
}

/* Receive exactly 'len' bytes; returns 0 on success, -1 on error */
static int recv_all(int fd, void* buf, size_t len) {
    uint8_t* p = (uint8_t*)buf;
    while (len > 0) {
        ssize_t n = recv(fd, p, len, 0);
        if (n <= 0) return -1;
        p   += n;
        len -= (size_t)n;
    }
    return 0;
}

/* Send a framed message: [BE-uint32 length][type byte][payload] */
static int send_msg(uint8_t type, const void* payload, uint32_t payload_len) {
    uint32_t length = htonl(1u + payload_len);
    if (send_all(g_sock_fd, &length, 4) != 0) return -1;
    if (send_all(g_sock_fd, &type, 1)   != 0) return -1;
    if (payload_len > 0) {
        if (send_all(g_sock_fd, payload, payload_len) != 0) return -1;
    }
    return 0;
}

/* Receive one framed message. Returns type byte, fills buf up to buf_size.
 * Returns -1 on error. */
static int recv_msg(void* buf, size_t buf_size, int flags) {
    uint32_t length_be;
    ssize_t  n;

    /* Peek/recv the 4-byte length */
    if (flags & MSG_DONTWAIT) {
        n = recv(g_sock_fd, &length_be, 4, MSG_DONTWAIT | MSG_PEEK);
        if (n <= 0) return -1;   /* nothing available or error */
        /* Now consume it */
        recv(g_sock_fd, &length_be, 4, 0);
    } else {
        if (recv_all(g_sock_fd, &length_be, 4) != 0) return -1;
    }

    uint32_t body_len = ntohl(length_be);
    if (body_len == 0) return -1;

    uint8_t type;
    if (recv_all(g_sock_fd, &type, 1) != 0) return -1;
    body_len -= 1;   /* subtract the type byte */

    if (body_len > 0) {
        size_t to_read = body_len < buf_size ? body_len : buf_size;
        if (recv_all(g_sock_fd, buf, to_read) != 0) return -1;
        /* Drain any excess we didn't want */
        if (body_len > to_read) {
            uint8_t discard[64];
            size_t  left = body_len - to_read;
            while (left > 0) {
                size_t chunk = left < sizeof(discard) ? left : sizeof(discard);
                if (recv_all(g_sock_fd, discard, chunk) != 0) return -1;
                left -= chunk;
            }
        }
    }
    return (int)(unsigned)type;
}

/* --------------------------------------------------------------------------
 * Public API
 * -------------------------------------------------------------------------- */

int gla_ipc_connect(void) {
    const char* socket_path = getenv("GLA_SOCKET_PATH");
    const char* shm_name    = getenv("GLA_SHM_NAME");

    if (!socket_path || !shm_name) {
        /* Passthrough mode — engine not configured */
        return -1;
    }

    /* Open shared memory */
    int shm_fd = shm_open(shm_name, O_RDWR, 0);
    if (shm_fd < 0) {
        fprintf(stderr, "[GLA] shm_open(%s) failed: %s\n", shm_name, strerror(errno));
        return -1;
    }

    /* Map just the header first to learn total size */
    void* hdr_map = mmap(NULL, sizeof(RingHeader), PROT_READ | PROT_WRITE,
                         MAP_SHARED, shm_fd, 0);
    if (hdr_map == MAP_FAILED) {
        fprintf(stderr, "[GLA] mmap header failed: %s\n", strerror(errno));
        close(shm_fd);
        return -1;
    }
    RingHeader hdr;
    memcpy(&hdr, hdr_map, sizeof(hdr));
    munmap(hdr_map, sizeof(RingHeader));

    if (hdr.magic != GLA_SHM_MAGIC) {
        fprintf(stderr, "[GLA] shm magic mismatch (got 0x%llx)\n",
                (unsigned long long)hdr.magic);
        close(shm_fd);
        return -1;
    }

    g_shm_size = (size_t)hdr.total_size;
    g_num_slots = hdr.num_slots;
    g_slot_size = hdr.slot_size;

    g_shm_base = mmap(NULL, g_shm_size, PROT_READ | PROT_WRITE,
                      MAP_SHARED, shm_fd, 0);
    close(shm_fd);
    if (g_shm_base == MAP_FAILED) {
        g_shm_base = NULL;
        fprintf(stderr, "[GLA] mmap full shm failed: %s\n", strerror(errno));
        return -1;
    }

    /* Connect Unix socket */
    g_sock_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (g_sock_fd < 0) {
        fprintf(stderr, "[GLA] socket() failed: %s\n", strerror(errno));
        munmap(g_shm_base, g_shm_size);
        g_shm_base = NULL;
        return -1;
    }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, socket_path, sizeof(addr.sun_path) - 1);

    if (connect(g_sock_fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        fprintf(stderr, "[GLA] connect(%s) failed: %s\n", socket_path, strerror(errno));
        close(g_sock_fd);
        g_sock_fd = -1;
        munmap(g_shm_base, g_shm_size);
        g_shm_base = NULL;
        return -1;
    }

    /* Send handshake */
    HandshakePayload hs;
    hs.protocol_version = htonl(PROTOCOL_VERSION);
    hs.api_type         = htonl(API_TYPE_GL);
    hs.pid              = htonl((uint32_t)getpid());

    if (send_msg(MSG_HANDSHAKE, &hs, sizeof(hs)) != 0) {
        fprintf(stderr, "[GLA] handshake send failed\n");
        close(g_sock_fd);
        g_sock_fd = -1;
        munmap(g_shm_base, g_shm_size);
        g_shm_base = NULL;
        return -1;
    }

    /* Wait for handshake OK/FAIL */
    uint8_t response_buf[16];
    int rtype = recv_msg(response_buf, sizeof(response_buf), 0);
    if (rtype != MSG_HANDSHAKE_OK) {
        fprintf(stderr, "[GLA] handshake rejected (type=%d)\n", rtype);
        close(g_sock_fd);
        g_sock_fd = -1;
        munmap(g_shm_base, g_shm_size);
        g_shm_base = NULL;
        return -1;
    }

    fprintf(stderr, "[GLA] IPC connected: shm=%s socket=%s slots=%u slot_size=%llu\n",
            shm_name, socket_path, g_num_slots, (unsigned long long)g_slot_size);
    return 0;
}

int gla_ipc_is_connected(void) {
    return g_sock_fd >= 0 && g_shm_base != NULL;
}

void* gla_ipc_claim_slot(uint32_t* slot_index) {
    if (!gla_ipc_is_connected()) return NULL;

    /* Round-robin scan for a FREE slot; CAS it to WRITING */
    for (uint32_t i = 0; i < g_num_slots; i++) {
        uint32_t idx = (g_next_write + i) % g_num_slots;
        SlotHeader* hdr = slot_header(idx);

        uint32_t expected = SLOT_FREE;
        if (atomic_compare_exchange_strong(&hdr->state, &expected, SLOT_WRITING)) {
            g_next_write = (idx + 1) % g_num_slots;
            *slot_index = idx;
            return slot_data(idx);
        }
    }
    return NULL;   /* ring buffer full */
}

void gla_ipc_commit_slot(uint32_t slot_index, uint64_t size) {
    if (!gla_ipc_is_connected()) return;
    SlotHeader* hdr = slot_header(slot_index);
    hdr->data_size = size;
    atomic_store(&hdr->state, SLOT_READY);
}

void gla_ipc_send_frame_ready(uint64_t frame_id, uint32_t slot_index) {
    if (!gla_ipc_is_connected()) return;

    FrameReadyPayload fr;
    /* FrameReadyPayload fields are sent as native endian to match the C++
     * engine which reads them the same way it wrote the struct */
    fr.frame_id       = frame_id;
    fr.shm_slot_index = slot_index;

    if (send_msg(MSG_FRAME_READY, &fr, sizeof(fr)) != 0) {
        fprintf(stderr, "[GLA] send FRAME_READY failed, disconnecting\n");
        gla_ipc_disconnect();
    }
}

int gla_ipc_should_pause(void) {
    if (!gla_ipc_is_connected()) return 0;

    ControlPayload ctrl;
    int rtype = recv_msg(&ctrl, sizeof(ctrl), MSG_DONTWAIT);
    if (rtype == MSG_CONTROL && ctrl.pause) {
        return 1;
    }
    return 0;
}

void gla_ipc_wait_resume(void) {
    if (!gla_ipc_is_connected()) return;

    ControlPayload ctrl;
    for (;;) {
        int rtype = recv_msg(&ctrl, sizeof(ctrl), 0);
        if (rtype < 0) {
            /* Socket closed or error — stop waiting */
            return;
        }
        if (rtype == MSG_CONTROL && ctrl.resume) {
            return;
        }
    }
}

void gla_ipc_disconnect(void) {
    if (g_sock_fd >= 0) {
        close(g_sock_fd);
        g_sock_fd = -1;
    }
    if (g_shm_base) {
        munmap(g_shm_base, g_shm_size);
        g_shm_base = NULL;
    }
    g_num_slots  = 0;
    g_slot_size  = 0;
    g_next_write = 0;
}
