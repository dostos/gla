#ifndef GPA_IPC_CLIENT_H
#define GPA_IPC_CLIENT_H

#include <stdint.h>

/* Connect to engine. Uses GPA_SOCKET_PATH and GPA_SHM_NAME env vars.
 * Returns 0 on success, -1 on failure (engine not running — shim works as
 * passthrough).
 *
 * Internally retries the Unix-socket connect()+handshake portion up to 5
 * times with backoff (50/100/200/400/800 ms; ~1.55 s worst-case wait) to
 * survive kernel socket-backlog pressure when many shim'd binaries race to
 * connect to the engine in parallel. The shm_open portion is one-shot —
 * if the engine isn't up at all we fail fast. On exhaustion of retries the
 * function logs a single message to stderr and returns -1; the shim falls
 * through to its existing passthrough/fail-open path. */
int gpa_ipc_connect(void);

/* Connect only the Unix-socket side and run the handshake, with the same
 * retry-with-backoff schedule as gpa_ipc_connect. Returns 0 on success, -1
 * on exhaustion. Exposed for unit tests; not for production callers. */
int gpa_ipc_connect_socket_with_retry(const char* socket_path);

/* Check if connected */
int gpa_ipc_is_connected(void);

/* Claim a shared memory write slot. Returns pointer to data area, or NULL if
 * no free slot. */
void* gpa_ipc_claim_slot(uint32_t* slot_index);

/* Commit a written slot with its data size */
void gpa_ipc_commit_slot(uint32_t slot_index, uint64_t size);

/* Send FRAME_READY message to engine */
void gpa_ipc_send_frame_ready(uint64_t frame_id, uint32_t slot_index);

/* Check if engine wants us to pause. Non-blocking. */
int gpa_ipc_should_pause(void);

/* Block until engine signals resume */
void gpa_ipc_wait_resume(void);

/* Disconnect */
void gpa_ipc_disconnect(void);

#endif /* GPA_IPC_CLIENT_H */
