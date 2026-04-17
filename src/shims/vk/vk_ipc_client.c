#define _GNU_SOURCE
#include "vk_ipc_client.h"

#include <arpa/inet.h>
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

/* --------------------------------------------------------------------------
 * Mirror of shm_ring_buffer.h layout (must stay in sync with C++ definitions)
 * -------------------------------------------------------------------------- */

#define SLOT_FREE    0u
#define SLOT_WRITING 1u
#define SLOT_READY   2u
#define SLOT_READING 3u

typedef struct {
    uint64_t magic;
    uint32_t num_slots;
    uint32_t _pad;
    uint64_t slot_size;
    uint64_t total_size;
} RingHeader;

#define GLA_SHM_MAGIC 0x474C415F53484D00ULL

typedef struct {
    _Atomic uint32_t state;
    uint32_t         _pad0;
    uint64_t         frame_id;
    uint64_t         data_size;
    uint8_t          _pad1[40];
} SlotHeader;

_Static_assert(sizeof(SlotHeader) == 64, "SlotHeader must be 64 bytes");

/* --------------------------------------------------------------------------
 * Wire protocol (mirrors protocol.h)
 * -------------------------------------------------------------------------- */

#define MSG_HANDSHAKE      1u
#define MSG_HANDSHAKE_OK   2u
#define MSG_HANDSHAKE_FAIL 3u
#define MSG_FRAME_READY    4u
#define MSG_CONTROL        5u

#define PROTOCOL_VERSION 1u
#define API_TYPE_VK      1u   /* Vulkan — differs from GL shim (0) */

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

static int      g_sock_fd    = -1;
static void    *g_shm_base   = NULL;
static size_t   g_shm_size   = 0;
static uint32_t g_num_slots  = 0;
static uint64_t g_slot_size  = 0;
static uint32_t g_next_write = 0;

/* --------------------------------------------------------------------------
 * Internal helpers
 * -------------------------------------------------------------------------- */

static SlotHeader *slot_header(uint32_t index) {
    /* Slot region starts at the first 64-byte-aligned offset after the 32-byte
     * RingHeader (i.e., offset 64).  Each slot is 64 (header) + slot_size. */
    uint8_t *base        = (uint8_t *)g_shm_base;
    size_t   slot_stride = (size_t)(64 + g_slot_size);
    return (SlotHeader *)(base + 64 + index * slot_stride);
}

static void *slot_data(uint32_t index) {
    return (uint8_t *)slot_header(index) + 64;
}

static int send_all(int fd, const void *buf, size_t len) {
    const uint8_t *p = (const uint8_t *)buf;
    while (len > 0) {
        ssize_t n = send(fd, p, len, MSG_NOSIGNAL);
        if (n <= 0) return -1;
        p   += n;
        len -= (size_t)n;
    }
    return 0;
}

static int recv_all(int fd, void *buf, size_t len) {
    uint8_t *p = (uint8_t *)buf;
    while (len > 0) {
        ssize_t n = recv(fd, p, len, 0);
        if (n <= 0) return -1;
        p   += n;
        len -= (size_t)n;
    }
    return 0;
}

static int send_msg(uint8_t type, const void *payload, uint32_t payload_len) {
    uint32_t length = htonl(1u + payload_len);
    if (send_all(g_sock_fd, &length, 4) != 0) return -1;
    if (send_all(g_sock_fd, &type,   1) != 0) return -1;
    if (payload_len > 0) {
        if (send_all(g_sock_fd, payload, payload_len) != 0) return -1;
    }
    return 0;
}

/* Returns message type byte, or -1 on error. */
static int recv_msg(void *buf, size_t buf_size, int flags) {
    uint32_t length_be;
    ssize_t  n;

    if (flags & MSG_DONTWAIT) {
        n = recv(g_sock_fd, &length_be, 4, MSG_DONTWAIT | MSG_PEEK);
        if (n <= 0) return -1;
        recv(g_sock_fd, &length_be, 4, 0);
    } else {
        if (recv_all(g_sock_fd, &length_be, 4) != 0) return -1;
    }

    uint32_t body_len = ntohl(length_be);
    if (body_len == 0) return -1;

    uint8_t type;
    if (recv_all(g_sock_fd, &type, 1) != 0) return -1;
    body_len -= 1;

    if (body_len > 0) {
        size_t to_read = body_len < buf_size ? body_len : buf_size;
        if (recv_all(g_sock_fd, buf, to_read) != 0) return -1;
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

int gla_vk_ipc_connect(void) {
    const char *socket_path = getenv("GLA_SOCKET_PATH");
    const char *shm_name    = getenv("GLA_SHM_NAME");

    if (!socket_path || !shm_name) {
        /* Engine not configured — run in passthrough mode. */
        return -1;
    }

    /* Open shared memory */
    int shm_fd = shm_open(shm_name, O_RDWR, 0);
    if (shm_fd < 0) {
        fprintf(stderr, "[GLA-VK] shm_open(%s) failed: %s\n",
                shm_name, strerror(errno));
        return -1;
    }

    /* Map header to discover total size */
    void *hdr_map = mmap(NULL, sizeof(RingHeader), PROT_READ | PROT_WRITE,
                         MAP_SHARED, shm_fd, 0);
    if (hdr_map == MAP_FAILED) {
        fprintf(stderr, "[GLA-VK] mmap header failed: %s\n", strerror(errno));
        close(shm_fd);
        return -1;
    }
    RingHeader hdr;
    memcpy(&hdr, hdr_map, sizeof(hdr));
    munmap(hdr_map, sizeof(RingHeader));

    if (hdr.magic != GLA_SHM_MAGIC) {
        fprintf(stderr, "[GLA-VK] shm magic mismatch (got 0x%llx)\n",
                (unsigned long long)hdr.magic);
        close(shm_fd);
        return -1;
    }

    g_shm_size  = (size_t)hdr.total_size;
    g_num_slots = hdr.num_slots;
    g_slot_size = hdr.slot_size;

    g_shm_base = mmap(NULL, g_shm_size, PROT_READ | PROT_WRITE,
                      MAP_SHARED, shm_fd, 0);
    close(shm_fd);
    if (g_shm_base == MAP_FAILED) {
        g_shm_base = NULL;
        fprintf(stderr, "[GLA-VK] mmap full shm failed: %s\n", strerror(errno));
        return -1;
    }

    /* Connect Unix domain socket */
    g_sock_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (g_sock_fd < 0) {
        fprintf(stderr, "[GLA-VK] socket() failed: %s\n", strerror(errno));
        munmap(g_shm_base, g_shm_size);
        g_shm_base = NULL;
        return -1;
    }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, socket_path, sizeof(addr.sun_path) - 1);

    if (connect(g_sock_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        fprintf(stderr, "[GLA-VK] connect(%s) failed: %s\n",
                socket_path, strerror(errno));
        close(g_sock_fd);
        g_sock_fd = -1;
        munmap(g_shm_base, g_shm_size);
        g_shm_base = NULL;
        return -1;
    }

    /* Send handshake — api_type = 1 (VK) */
    HandshakePayload hs;
    hs.protocol_version = htonl(PROTOCOL_VERSION);
    hs.api_type         = htonl(API_TYPE_VK);
    hs.pid              = htonl((uint32_t)getpid());

    if (send_msg(MSG_HANDSHAKE, &hs, sizeof(hs)) != 0) {
        fprintf(stderr, "[GLA-VK] handshake send failed\n");
        goto fail_connected;
    }

    /* Wait for HANDSHAKE_OK / HANDSHAKE_FAIL */
    uint8_t response_buf[16];
    int rtype = recv_msg(response_buf, sizeof(response_buf), 0);
    if (rtype != MSG_HANDSHAKE_OK) {
        fprintf(stderr, "[GLA-VK] handshake rejected (type=%d)\n", rtype);
        goto fail_connected;
    }

    fprintf(stderr,
            "[GLA-VK] IPC connected: shm=%s socket=%s slots=%u slot_size=%llu\n",
            shm_name, socket_path, g_num_slots,
            (unsigned long long)g_slot_size);
    return 0;

fail_connected:
    close(g_sock_fd);
    g_sock_fd = -1;
    munmap(g_shm_base, g_shm_size);
    g_shm_base = NULL;
    return -1;
}

int gla_vk_ipc_is_connected(void) {
    return g_sock_fd >= 0 && g_shm_base != NULL;
}

void *gla_vk_ipc_claim_slot(uint32_t *slot_index) {
    if (!gla_vk_ipc_is_connected()) return NULL;

    for (uint32_t i = 0; i < g_num_slots; i++) {
        uint32_t idx = (g_next_write + i) % g_num_slots;
        SlotHeader *hdr = slot_header(idx);

        uint32_t expected = SLOT_FREE;
        if (atomic_compare_exchange_strong(&hdr->state, &expected, SLOT_WRITING)) {
            g_next_write = (idx + 1) % g_num_slots;
            *slot_index  = idx;
            return slot_data(idx);
        }
    }
    return NULL; /* ring buffer full */
}

void gla_vk_ipc_commit_slot(uint32_t slot_index, uint64_t size) {
    if (!gla_vk_ipc_is_connected()) return;
    SlotHeader *hdr = slot_header(slot_index);
    hdr->data_size  = size;
    atomic_store(&hdr->state, SLOT_READY);
}

void gla_vk_ipc_send_frame_ready(uint64_t frame_id, uint32_t slot_index) {
    if (!gla_vk_ipc_is_connected()) return;

    FrameReadyPayload fr;
    fr.frame_id       = frame_id;
    fr.shm_slot_index = slot_index;

    if (send_msg(MSG_FRAME_READY, &fr, sizeof(fr)) != 0) {
        fprintf(stderr, "[GLA-VK] send FRAME_READY failed, disconnecting\n");
        gla_vk_ipc_disconnect();
    }
}

int gla_vk_ipc_should_pause(void) {
    if (!gla_vk_ipc_is_connected()) return 0;

    ControlPayload ctrl;
    int rtype = recv_msg(&ctrl, sizeof(ctrl), MSG_DONTWAIT);
    if (rtype == MSG_CONTROL && ctrl.pause) {
        return 1;
    }
    return 0;
}

void gla_vk_ipc_wait_resume(void) {
    if (!gla_vk_ipc_is_connected()) return;

    ControlPayload ctrl;
    for (;;) {
        int rtype = recv_msg(&ctrl, sizeof(ctrl), 0);
        if (rtype < 0) return;
        if (rtype == MSG_CONTROL && ctrl.resume) return;
    }
}

void gla_vk_ipc_disconnect(void) {
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
