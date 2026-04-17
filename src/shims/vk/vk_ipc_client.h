#ifndef VK_IPC_CLIENT_H
#define VK_IPC_CLIENT_H

/*
 * vk_ipc_client.h — IPC client for the GLA Vulkan layer.
 *
 * Implements the same SHM ring buffer + Unix socket protocol as the GL shim
 * (src/shims/gl/ipc_client.c).  The only difference is the api_type field
 * in the handshake (1 = VK instead of 0 = GL).
 */

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Connect to the GLA engine.
 * Reads GLA_SOCKET_PATH and GLA_SHM_NAME from the environment.
 * Returns 0 on success, -1 if the engine is not running (passthrough mode).
 */
int gla_vk_ipc_connect(void);

/* Returns non-zero if connected. */
int gla_vk_ipc_is_connected(void);

/*
 * Claim a FREE slot in the SHM ring buffer.
 * Returns a pointer to the data region, or NULL if the buffer is full.
 * *slot_index is set to the claimed slot on success.
 */
void *gla_vk_ipc_claim_slot(uint32_t *slot_index);

/*
 * Commit a slot that was previously claimed with gla_vk_ipc_claim_slot.
 * 'size' is the number of valid bytes written into the data region.
 */
void gla_vk_ipc_commit_slot(uint32_t slot_index, uint64_t size);

/*
 * Send MSG_FRAME_READY to the engine over the control socket.
 */
void gla_vk_ipc_send_frame_ready(uint64_t frame_id, uint32_t slot_index);

/*
 * Non-blocking check: returns 1 if the engine sent a MSG_CONTROL(pause).
 */
int gla_vk_ipc_should_pause(void);

/*
 * Blocking wait until the engine sends MSG_CONTROL(resume).
 */
void gla_vk_ipc_wait_resume(void);

/* Disconnect and release all resources. */
void gla_vk_ipc_disconnect(void);

#ifdef __cplusplus
}
#endif

#endif /* VK_IPC_CLIENT_H */
