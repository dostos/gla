#define _GNU_SOURCE
#include <stdio.h>
#include <unistd.h>
#include "gl_wrappers.h"
#include "shadow_state.h"
#include "ipc_client.h"

GlaRealGlFuncs gla_real_gl = {0};
GlaShadowState gla_shadow = {0};
static int gla_wrappers_ready = 0;
static int gla_ipc_ready = 0;

pid_t gla_get_init_pid(void) {
    /* No longer used for fork guard — kept for ABI compat */
    return getpid();
}

/* Phase 1: resolve real GL function pointers + init shadow state.
 * Called from every wrapper function. Safe to call from any process. */
void gla_init(void) {
    if (gla_wrappers_ready) return;
    gla_wrappers_ready = 1;
    gla_wrappers_init();
    gla_shadow_init(&gla_shadow);
}

/* Phase 2: connect IPC to engine. Only called from glXSwapBuffers,
 * which is only hit by the process that actually does rendering.
 * This naturally avoids the fork problem — child processes that
 * never render never connect to the engine. */
void gla_ensure_ipc(void) {
    if (gla_ipc_ready) return;
    gla_ipc_ready = 1;
    gla_ipc_connect();
    fprintf(stderr, "[OpenGPA] Shim active (pid=%d)\n", getpid());
}

/* NO constructor — init is lazy on first GL call.
 * This avoids the fork issue where X11/DRI child processes
 * would initialize and connect to the engine unnecessarily. */
