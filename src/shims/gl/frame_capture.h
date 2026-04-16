#ifndef GLA_FRAME_CAPTURE_H
#define GLA_FRAME_CAPTURE_H

/* Called from glXSwapBuffers wrapper. Captures the current framebuffer (color
 * + depth) into a shared memory slot and notifies the engine via the IPC
 * socket. No-op when the IPC client is not connected (passthrough mode). */
void gla_frame_on_swap(void);

#endif /* GLA_FRAME_CAPTURE_H */
