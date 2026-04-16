#include "frame_capture.h"
#include "ipc_client.h"
#include "gl_wrappers.h"
#include "shadow_state.h"

#include <stdint.h>
#include <stddef.h>

/* GL constants not pulled from GL headers */
#define GL_RGBA            0x1908
#define GL_UNSIGNED_BYTE   0x1401
/* GL_FLOAT 0x1406 already defined in shadow_state.h */
#define GL_DEPTH_COMPONENT 0x1902
#define GL_VIEWPORT        0x0BA2

/* Globals defined in gl_shim.c */
extern GlaShadowState   gla_shadow;
extern GlaRealGlFuncs   gla_real_gl;

void gla_frame_on_swap(void) {
    if (!gla_ipc_is_connected()) return;

    uint32_t slot_index;
    void* slot = gla_ipc_claim_slot(&slot_index);
    if (!slot) return;   /* ring buffer full — skip this frame */

    /* Query current viewport dimensions */
    GLint viewport[4];
    gla_real_gl.glGetIntegerv(GL_VIEWPORT, viewport);
    int width  = (int)viewport[2];
    int height = (int)viewport[3];

    /* Guard against degenerate viewports */
    if (width <= 0 || height <= 0) {
        /* Release the slot so it goes back to FREE without confusing the engine */
        gla_ipc_commit_slot(slot_index, 0);
        gla_ipc_send_frame_ready(gla_shadow.frame_number, slot_index);
        return;
    }

    /* Write frame data into the shm slot.
     * Layout:
     *   [0..3]   width  (uint32_t)
     *   [4..7]   height (uint32_t)
     *   [8 ..]   color data (width * height * 4 bytes, GL_RGBA / GL_UNSIGNED_BYTE)
     *   [8 + w*h*4 ..] depth data (width * height * 4 bytes, GL_DEPTH_COMPONENT / GL_FLOAT)
     */
    uint8_t*  ptr    = (uint8_t*)slot;
    uint32_t* header = (uint32_t*)ptr;
    header[0] = (uint32_t)width;
    header[1] = (uint32_t)height;
    ptr += 8;

    /* Color buffer */
    gla_real_gl.glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, ptr);
    ptr += (size_t)width * (size_t)height * 4u;

    /* Depth buffer */
    gla_real_gl.glReadPixels(0, 0, width, height, GL_DEPTH_COMPONENT, GL_FLOAT, ptr);
    ptr += (size_t)width * (size_t)height * 4u;

    uint64_t total_size = (uint64_t)((uintptr_t)ptr - (uintptr_t)slot);

    gla_ipc_commit_slot(slot_index, total_size);
    gla_ipc_send_frame_ready(gla_shadow.frame_number, slot_index);

    /* Check for pause request from engine (non-blocking) */
    if (gla_ipc_should_pause()) {
        gla_ipc_wait_resume();
    }
}
