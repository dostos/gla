#ifndef VK_CAPTURE_H
#define VK_CAPTURE_H

/*
 * vk_capture.h — Frame capture and draw call recording for the OpenGPA Vulkan
 * layer.
 *
 * At vkQueuePresentKHR the layer:
 *   1. Reads back the swapchain image into a host-visible buffer.
 *   2. Writes framebuffer + draw call metadata into a SHM slot.
 *   3. Sends MSG_FRAME_READY to the engine over the control socket.
 */

#include <vulkan/vulkan.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Maximum draw calls recorded per frame (matches GL shim ceiling). */
#define GPA_VK_MAX_DRAW_CALLS 1024

/* -------------------------------------------------------------------------
 * Draw call snapshot stored during command buffer recording.
 * ---------------------------------------------------------------------- */
typedef struct GpaVkDrawCall {
    uint32_t id;
    uint32_t vertex_count;
    uint32_t index_count;
    uint32_t instance_count;
    uint32_t first_vertex;
    uint32_t first_index;
    uint32_t first_instance;

    /* Pipeline state at recording time */
    VkPipeline    pipeline;
    VkPipelineBindPoint bind_point;

    /* Render pass info */
    uint32_t subpass;
} GpaVkDrawCall;

/* -------------------------------------------------------------------------
 * Per-command-buffer recording state.
 * ---------------------------------------------------------------------- */
typedef struct GpaVkCmdBufState {
    VkCommandBuffer cmd_buf;
    GpaVkDrawCall   draws[GPA_VK_MAX_DRAW_CALLS];
    uint32_t        draw_count;

    /* Tracked pipeline */
    VkPipeline      current_pipeline;
    VkPipelineBindPoint current_bind_point;

    /* Current render pass subpass index */
    uint32_t        current_subpass;
} GpaVkCmdBufState;

/* -------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

/* Called once on layer init to set up the capture module. */
void gpa_capture_init(void);

/* Called on layer teardown. */
void gpa_capture_shutdown(void);

/* Allocate (or recycle) per-command-buffer state. */
GpaVkCmdBufState *gpa_capture_cmd_buf_begin(VkCommandBuffer cmd_buf);

/* Free per-command-buffer state. */
void gpa_capture_cmd_buf_end(VkCommandBuffer cmd_buf);

/* Retrieve existing state (may return NULL if not tracked). */
GpaVkCmdBufState *gpa_capture_cmd_buf_get(VkCommandBuffer cmd_buf);

/* Record a draw call into the per-command-buffer state. */
void gpa_capture_record_draw(VkCommandBuffer cmd_buf,
                              uint32_t vertex_count,
                              uint32_t instance_count,
                              uint32_t first_vertex,
                              uint32_t first_instance);

void gpa_capture_record_draw_indexed(VkCommandBuffer cmd_buf,
                                      uint32_t index_count,
                                      uint32_t instance_count,
                                      uint32_t first_index,
                                      int32_t  vertex_offset,
                                      uint32_t first_instance);

/* Track pipeline bind. */
void gpa_capture_bind_pipeline(VkCommandBuffer cmd_buf,
                                VkPipelineBindPoint bind_point,
                                VkPipeline pipeline);

/* Track render pass boundaries. */
void gpa_capture_begin_render_pass(VkCommandBuffer cmd_buf);
void gpa_capture_end_render_pass(VkCommandBuffer cmd_buf);

/* Called on vkQueuePresentKHR — perform readback and IPC send.
 *
 * If `skip_pixel_readback` is non-zero, the pixel-copy GPU readback is
 * skipped entirely and only metadata (extent, format, draw counts) is
 * forwarded to the engine. This is the right call for emulated
 * (in-layer) headless swapchains — their VkImages contain whatever the
 * compositor left behind, the pre-present layout is non-standard, and
 * waiting on a fence for our staging copy can take seconds in
 * compositor-style apps (chromium). */
void gpa_capture_on_present(VkQueue           queue,
                             VkDevice          device,
                             VkSwapchainKHR    swapchain,
                             uint32_t          image_index,
                             VkImage           swapchain_image,
                             VkExtent2D        extent,
                             VkFormat          image_format,
                             int               skip_pixel_readback);

/* Accumulate draw calls from submitted command buffers into the frame buffer.
 * Called from vkQueueSubmit so we can harvest metadata even before present. */
void gpa_capture_queue_submit(uint32_t cmd_buf_count,
                               const VkCommandBuffer *cmd_bufs);

#ifdef __cplusplus
}
#endif

#endif /* VK_CAPTURE_H */
