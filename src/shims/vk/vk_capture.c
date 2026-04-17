#define _GNU_SOURCE
#include "vk_capture.h"
#include "vk_dispatch.h"
#include "vk_ipc_client.h"

#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* --------------------------------------------------------------------------
 * Per-frame accumulated draw calls (from all submitted command buffers)
 * -------------------------------------------------------------------------- */

static GlaVkDrawCall  g_frame_draws[GLA_VK_MAX_DRAW_CALLS];
static uint32_t       g_frame_draw_count = 0;
static uint64_t       g_frame_id         = 0;
static pthread_mutex_t g_frame_mutex     = PTHREAD_MUTEX_INITIALIZER;

/* --------------------------------------------------------------------------
 * Per-command-buffer state registry (simple open-addressing hash table)
 * -------------------------------------------------------------------------- */

#define CMD_TABLE_CAPACITY 256
#define CMD_TABLE_MASK     (CMD_TABLE_CAPACITY - 1)

typedef struct {
    VkCommandBuffer    key;
    GlaVkCmdBufState   state;
} CmdBufEntry;

static CmdBufEntry     g_cmd_table[CMD_TABLE_CAPACITY];
static pthread_mutex_t g_cmd_mutex = PTHREAD_MUTEX_INITIALIZER;

static GlaVkCmdBufState *cmd_table_get_locked(VkCommandBuffer cmd_buf) {
    size_t slot = ((uintptr_t)cmd_buf >> 3) & CMD_TABLE_MASK;
    for (size_t i = 0; i < CMD_TABLE_CAPACITY; i++) {
        size_t idx = (slot + i) & CMD_TABLE_MASK;
        if (g_cmd_table[idx].key == VK_NULL_HANDLE) return NULL;
        if (g_cmd_table[idx].key == cmd_buf) return &g_cmd_table[idx].state;
    }
    return NULL;
}

/* --------------------------------------------------------------------------
 * Public API
 * -------------------------------------------------------------------------- */

void gla_capture_init(void) {
    memset(g_cmd_table,   0, sizeof(g_cmd_table));
    memset(g_frame_draws, 0, sizeof(g_frame_draws));
    g_frame_draw_count = 0;
    g_frame_id         = 0;
}

void gla_capture_shutdown(void) {
    /* Nothing heap-allocated; just zero the tables. */
    memset(g_cmd_table,   0, sizeof(g_cmd_table));
    memset(g_frame_draws, 0, sizeof(g_frame_draws));
}

GlaVkCmdBufState *gla_capture_cmd_buf_begin(VkCommandBuffer cmd_buf) {
    pthread_mutex_lock(&g_cmd_mutex);

    size_t slot = ((uintptr_t)cmd_buf >> 3) & CMD_TABLE_MASK;
    for (size_t i = 0; i < CMD_TABLE_CAPACITY; i++) {
        size_t idx = (slot + i) & CMD_TABLE_MASK;
        if (g_cmd_table[idx].key == VK_NULL_HANDLE ||
            g_cmd_table[idx].key == cmd_buf) {
            g_cmd_table[idx].key = cmd_buf;
            GlaVkCmdBufState *s  = &g_cmd_table[idx].state;
            memset(s, 0, sizeof(*s));
            s->cmd_buf    = cmd_buf;
            pthread_mutex_unlock(&g_cmd_mutex);
            return s;
        }
    }
    fprintf(stderr, "[GLA-VK] cmd_buf table full\n");
    pthread_mutex_unlock(&g_cmd_mutex);
    return NULL;
}

void gla_capture_cmd_buf_end(VkCommandBuffer cmd_buf) {
    pthread_mutex_lock(&g_cmd_mutex);
    size_t slot = ((uintptr_t)cmd_buf >> 3) & CMD_TABLE_MASK;
    for (size_t i = 0; i < CMD_TABLE_CAPACITY; i++) {
        size_t idx = (slot + i) & CMD_TABLE_MASK;
        if (g_cmd_table[idx].key == VK_NULL_HANDLE) break;
        if (g_cmd_table[idx].key == cmd_buf) {
            g_cmd_table[idx].key = VK_NULL_HANDLE;
            break;
        }
    }
    pthread_mutex_unlock(&g_cmd_mutex);
}

GlaVkCmdBufState *gla_capture_cmd_buf_get(VkCommandBuffer cmd_buf) {
    pthread_mutex_lock(&g_cmd_mutex);
    GlaVkCmdBufState *s = cmd_table_get_locked(cmd_buf);
    pthread_mutex_unlock(&g_cmd_mutex);
    return s;
}

void gla_capture_record_draw(VkCommandBuffer cmd_buf,
                              uint32_t vertex_count,
                              uint32_t instance_count,
                              uint32_t first_vertex,
                              uint32_t first_instance) {
    pthread_mutex_lock(&g_cmd_mutex);
    GlaVkCmdBufState *s = cmd_table_get_locked(cmd_buf);
    if (s && s->draw_count < GLA_VK_MAX_DRAW_CALLS) {
        GlaVkDrawCall *d   = &s->draws[s->draw_count];
        d->id              = s->draw_count;
        d->vertex_count    = vertex_count;
        d->index_count     = 0;
        d->instance_count  = instance_count;
        d->first_vertex    = first_vertex;
        d->first_index     = 0;
        d->first_instance  = first_instance;
        d->pipeline        = s->current_pipeline;
        d->bind_point      = s->current_bind_point;
        d->subpass         = s->current_subpass;
        s->draw_count++;
    }
    pthread_mutex_unlock(&g_cmd_mutex);
}

void gla_capture_record_draw_indexed(VkCommandBuffer cmd_buf,
                                      uint32_t index_count,
                                      uint32_t instance_count,
                                      uint32_t first_index,
                                      int32_t  vertex_offset,
                                      uint32_t first_instance) {
    (void)vertex_offset; /* not recorded in MVP metadata */
    pthread_mutex_lock(&g_cmd_mutex);
    GlaVkCmdBufState *s = cmd_table_get_locked(cmd_buf);
    if (s && s->draw_count < GLA_VK_MAX_DRAW_CALLS) {
        GlaVkDrawCall *d   = &s->draws[s->draw_count];
        d->id              = s->draw_count;
        d->vertex_count    = 0;
        d->index_count     = index_count;
        d->instance_count  = instance_count;
        d->first_vertex    = 0;
        d->first_index     = first_index;
        d->first_instance  = first_instance;
        d->pipeline        = s->current_pipeline;
        d->bind_point      = s->current_bind_point;
        d->subpass         = s->current_subpass;
        s->draw_count++;
    }
    pthread_mutex_unlock(&g_cmd_mutex);
}

void gla_capture_bind_pipeline(VkCommandBuffer     cmd_buf,
                                VkPipelineBindPoint bind_point,
                                VkPipeline          pipeline) {
    pthread_mutex_lock(&g_cmd_mutex);
    GlaVkCmdBufState *s = cmd_table_get_locked(cmd_buf);
    if (s) {
        s->current_pipeline   = pipeline;
        s->current_bind_point = bind_point;
    }
    pthread_mutex_unlock(&g_cmd_mutex);
}

void gla_capture_begin_render_pass(VkCommandBuffer cmd_buf) {
    /* Subpass index resets at render pass begin; already 0 from memset. */
    (void)cmd_buf;
}

void gla_capture_end_render_pass(VkCommandBuffer cmd_buf) {
    pthread_mutex_lock(&g_cmd_mutex);
    GlaVkCmdBufState *s = cmd_table_get_locked(cmd_buf);
    if (s) s->current_subpass = 0;
    pthread_mutex_unlock(&g_cmd_mutex);
}

void gla_capture_queue_submit(uint32_t               cmd_buf_count,
                               const VkCommandBuffer *cmd_bufs) {
    if (!gla_vk_ipc_is_connected()) return;

    pthread_mutex_lock(&g_cmd_mutex);
    pthread_mutex_lock(&g_frame_mutex);

    for (uint32_t b = 0; b < cmd_buf_count; b++) {
        GlaVkCmdBufState *s = cmd_table_get_locked(cmd_bufs[b]);
        if (!s) continue;

        for (uint32_t d = 0; d < s->draw_count; d++) {
            if (g_frame_draw_count >= GLA_VK_MAX_DRAW_CALLS) break;
            g_frame_draws[g_frame_draw_count]     = s->draws[d];
            g_frame_draws[g_frame_draw_count].id  = g_frame_draw_count;
            g_frame_draw_count++;
        }
    }

    pthread_mutex_unlock(&g_frame_mutex);
    pthread_mutex_unlock(&g_cmd_mutex);
}

/* --------------------------------------------------------------------------
 * Serialise Vulkan draw calls into a byte buffer.
 *
 * Wire format (per draw call):
 *   uint32  id
 *   uint32  vertex_count
 *   uint32  index_count
 *   uint32  instance_count
 *   uint32  first_vertex
 *   uint32  first_index
 *   uint32  first_instance
 *   uint64  pipeline (handle as uint64)
 *   uint32  bind_point
 *   uint32  subpass
 *
 * Preceded by uint32 draw_call_count.
 * -------------------------------------------------------------------------- */

static size_t serialise_vk_draw_calls(uint8_t *buf, size_t buf_max,
                                       const GlaVkDrawCall *draws,
                                       uint32_t count) {
    uint8_t *p   = buf;
    uint8_t *end = buf + buf_max;

    if (p + 4 > end) return 0;
    memcpy(p, &count, 4);
    p += 4;

    for (uint32_t i = 0; i < count; i++) {
        if (p + 44 > end) break; /* 9*uint32 + 1*uint64 = 44 bytes */
        const GlaVkDrawCall *d = &draws[i];

        memcpy(p, &d->id,             4); p += 4;
        memcpy(p, &d->vertex_count,   4); p += 4;
        memcpy(p, &d->index_count,    4); p += 4;
        memcpy(p, &d->instance_count, 4); p += 4;
        memcpy(p, &d->first_vertex,   4); p += 4;
        memcpy(p, &d->first_index,    4); p += 4;
        memcpy(p, &d->first_instance, 4); p += 4;

        uint64_t pipeline_u64 = (uint64_t)(uintptr_t)d->pipeline;
        memcpy(p, &pipeline_u64,      8); p += 8;

        uint32_t bind_point = (uint32_t)d->bind_point;
        memcpy(p, &bind_point,        4); p += 4;
        memcpy(p, &d->subpass,        4); p += 4;
    }
    return (size_t)(p - buf);
}

/* --------------------------------------------------------------------------
 * gla_capture_on_present — main capture path called from vkQueuePresentKHR
 * -------------------------------------------------------------------------- */

void gla_capture_on_present(VkQueue        queue,
                             VkDevice       device,
                             VkSwapchainKHR swapchain,
                             uint32_t       image_index,
                             VkImage        swapchain_image,
                             VkExtent2D     extent,
                             VkFormat       image_format) {
    (void)swapchain;     /* used for context only */
    (void)image_index;
    (void)image_format;

    if (!gla_vk_ipc_is_connected()) goto reset_frame;

    GlaDeviceDispatch *dev_disp = gla_device_dispatch_get(device);
    if (!dev_disp) goto reset_frame;

    /* Claim a SHM slot */
    uint32_t slot_index;
    void    *slot = gla_vk_ipc_claim_slot(&slot_index);
    if (!slot) {
        fprintf(stderr, "[GLA-VK] SHM ring buffer full, skipping frame %llu\n",
                (unsigned long long)g_frame_id);
        goto reset_frame;
    }

    /* ------------------------------------------------------------------ */
    /* Framebuffer readback                                                 */
    /*                                                                      */
    /* Strategy:                                                            */
    /*  1. Create a host-visible staging buffer sized for the image.        */
    /*  2. Create a temporary command pool + command buffer.                */
    /*  3. Transition the swapchain image to TRANSFER_SRC_OPTIMAL.         */
    /*  4. vkCmdCopyImageToBuffer.                                          */
    /*  5. Transition back to PRESENT_SRC_KHR.                             */
    /*  6. Submit with a fence; wait on CPU.                                */
    /*  7. Map staging buffer and copy into the SHM slot.                  */
    /* ------------------------------------------------------------------ */

    uint32_t width  = extent.width;
    uint32_t height = extent.height;

    /* Conservative: 4 bytes/pixel (RGBA8).  Most swapchain formats are BGRA8
     * or RGBA8 — we record the raw bytes without conversion for now. */
    VkDeviceSize pixel_bytes = (VkDeviceSize)width * height * 4u;

    /* Slot layout mirrors the GL shim:
     *   [0..3]   width   (uint32)
     *   [4..7]   height  (uint32)
     *   [8..]    pixel data (pixel_bytes bytes)
     *   [8+pb..] draw call metadata
     */
    uint8_t  *ptr        = (uint8_t *)slot;
    uint32_t *hdr_words  = (uint32_t *)ptr;
    hdr_words[0] = width;
    hdr_words[1] = height;
    ptr += 8;

    /* Allocate staging buffer */
    VkBuffer       staging_buf = VK_NULL_HANDLE;
    VkDeviceMemory staging_mem = VK_NULL_HANDLE;

    VkBufferCreateInfo buf_info = {0};
    buf_info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    buf_info.size  = pixel_bytes;
    buf_info.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    buf_info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;

    VkResult res = dev_disp->CreateBuffer(device, &buf_info, NULL, &staging_buf);
    if (res != VK_SUCCESS) {
        fprintf(stderr, "[GLA-VK] CreateBuffer failed (%d), skipping readback\n",
                res);
        goto write_metadata_only;
    }

    VkMemoryRequirements mem_req;
    dev_disp->GetBufferMemoryRequirements(device, staging_buf, &mem_req);

    /* Find HOST_VISIBLE | HOST_COHERENT memory type */
    VkPhysicalDeviceMemoryProperties mem_props;
    /* We stored the physical device handle in the dispatch table; retrieve it
     * by calling GetPhysicalDeviceMemoryProperties via the instance chain.
     * For simplicity in M5 MVP we get it from the device dispatch. */
    /* Use vkGetPhysicalDeviceMemoryProperties directly */
    {
        /* We need the instance to call this.  Since we only have the device
         * dispatch, use a workaround: call through a temporary fn ptr obtained
         * via GetInstanceProcAddr stored in the instance table.
         * For M5 MVP, iterate device dispatch physical device handle. */
        VkPhysicalDevice phys = dev_disp->physical_device;
        if (phys == VK_NULL_HANDLE) {
            fprintf(stderr, "[GLA-VK] no physical device in dispatch, skipping readback\n");
            dev_disp->DestroyBuffer(device, staging_buf, NULL);
            goto write_metadata_only;
        }

        /* Obtain GetPhysicalDeviceMemoryProperties fn via instance */
        /* We stored it on the device dispatch as a placeholder; look up
         * through a raw function pointer call to avoid dependency on instance
         * tables here. Use the Vulkan global loader symbol directly. */
        typedef void (VKAPI_PTR *PFN_GetPhysDevMemProps)(
            VkPhysicalDevice, VkPhysicalDeviceMemoryProperties *);

        /* Resolve via device's GetDeviceProcAddr chain won't work for phys-dev
         * functions.  Use the dynamic linker's copy of the loader symbol. */
        extern PFN_vkVoidFunction vkGetInstanceProcAddr(VkInstance, const char *);
        /* We can't easily call instance-level functions here without storing the
         * instance.  Use the simpler approach: cast to a raw function. */
        /* FALLBACK: call through the vkGetPhysicalDeviceMemoryProperties that
         * the loader exposes as a global weak symbol. */
        PFN_GetPhysDevMemProps fn_get_props =
            (PFN_GetPhysDevMemProps)(void(*)(void))
            vkGetInstanceProcAddr(VK_NULL_HANDLE,
                                  "vkGetPhysicalDeviceMemoryProperties");
        if (!fn_get_props) {
            fprintf(stderr, "[GLA-VK] cannot resolve GetPhysicalDeviceMemoryProperties\n");
            dev_disp->DestroyBuffer(device, staging_buf, NULL);
            goto write_metadata_only;
        }
        fn_get_props(phys, &mem_props);
    }

    /* Select memory type */
    uint32_t mem_type = UINT32_MAX;
    VkMemoryPropertyFlags required =
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    for (uint32_t i = 0; i < mem_props.memoryTypeCount; i++) {
        if ((mem_req.memoryTypeBits & (1u << i)) &&
            (mem_props.memoryTypes[i].propertyFlags & required) == required) {
            mem_type = i;
            break;
        }
    }
    if (mem_type == UINT32_MAX) {
        fprintf(stderr, "[GLA-VK] no host-visible memory type found\n");
        dev_disp->DestroyBuffer(device, staging_buf, NULL);
        goto write_metadata_only;
    }

    VkMemoryAllocateInfo alloc_info = {0};
    alloc_info.sType           = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    alloc_info.allocationSize  = mem_req.size;
    alloc_info.memoryTypeIndex = mem_type;

    res = dev_disp->AllocateMemory(device, &alloc_info, NULL, &staging_mem);
    if (res != VK_SUCCESS) {
        fprintf(stderr, "[GLA-VK] AllocateMemory failed (%d)\n", res);
        dev_disp->DestroyBuffer(device, staging_buf, NULL);
        goto write_metadata_only;
    }
    dev_disp->BindBufferMemory(device, staging_buf, staging_mem, 0);

    /* Create a transient command pool + command buffer */
    VkCommandPool   cmd_pool = VK_NULL_HANDLE;
    VkCommandBuffer cmd_buf  = VK_NULL_HANDLE;

    /* Get the queue family index.  For M5 MVP we use family 0 (safe default
     * for single-queue apps; production code would track the queue family). */
    VkCommandPoolCreateInfo pool_info = {0};
    pool_info.sType            = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    pool_info.flags            = VK_COMMAND_POOL_CREATE_TRANSIENT_BIT;
    pool_info.queueFamilyIndex = 0;

    res = dev_disp->CreateCommandPool(device, &pool_info, NULL, &cmd_pool);
    if (res != VK_SUCCESS) {
        fprintf(stderr, "[GLA-VK] CreateCommandPool failed (%d)\n", res);
        goto cleanup_mem;
    }

    VkCommandBufferAllocateInfo cb_alloc = {0};
    cb_alloc.sType              = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    cb_alloc.commandPool        = cmd_pool;
    cb_alloc.level              = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    cb_alloc.commandBufferCount = 1;

    res = dev_disp->AllocateCommandBuffers(device, &cb_alloc, &cmd_buf);
    if (res != VK_SUCCESS) {
        fprintf(stderr, "[GLA-VK] AllocateCommandBuffers failed (%d)\n", res);
        goto cleanup_pool;
    }

    VkCommandBufferBeginInfo begin_info = {0};
    begin_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    begin_info.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    dev_disp->BeginCommandBuffer(cmd_buf, &begin_info);

    /* Transition swapchain image: PRESENT_SRC → TRANSFER_SRC */
    VkImageMemoryBarrier barrier_to_src = {0};
    barrier_to_src.sType               = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier_to_src.srcAccessMask       = VK_ACCESS_MEMORY_READ_BIT;
    barrier_to_src.dstAccessMask       = VK_ACCESS_TRANSFER_READ_BIT;
    barrier_to_src.oldLayout           = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
    barrier_to_src.newLayout           = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    barrier_to_src.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier_to_src.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier_to_src.image               = swapchain_image;
    barrier_to_src.subresourceRange.aspectMask     = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier_to_src.subresourceRange.baseMipLevel   = 0;
    barrier_to_src.subresourceRange.levelCount     = 1;
    barrier_to_src.subresourceRange.baseArrayLayer = 0;
    barrier_to_src.subresourceRange.layerCount     = 1;

    dev_disp->CmdPipelineBarrier(cmd_buf,
        VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,
        VK_PIPELINE_STAGE_TRANSFER_BIT,
        0, 0, NULL, 0, NULL, 1, &barrier_to_src);

    /* Copy image to staging buffer */
    VkBufferImageCopy copy_region = {0};
    copy_region.bufferOffset                    = 0;
    copy_region.bufferRowLength                 = 0;  /* tightly packed */
    copy_region.bufferImageHeight               = 0;
    copy_region.imageSubresource.aspectMask     = VK_IMAGE_ASPECT_COLOR_BIT;
    copy_region.imageSubresource.mipLevel       = 0;
    copy_region.imageSubresource.baseArrayLayer = 0;
    copy_region.imageSubresource.layerCount     = 1;
    copy_region.imageOffset.x                   = 0;
    copy_region.imageOffset.y                   = 0;
    copy_region.imageOffset.z                   = 0;
    copy_region.imageExtent.width               = width;
    copy_region.imageExtent.height              = height;
    copy_region.imageExtent.depth               = 1;

    dev_disp->CmdCopyImageToBuffer(cmd_buf, swapchain_image,
        VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
        staging_buf, 1, &copy_region);

    /* Transition back to PRESENT_SRC */
    VkImageMemoryBarrier barrier_to_present = {0};
    barrier_to_present.sType               = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier_to_present.srcAccessMask       = VK_ACCESS_TRANSFER_READ_BIT;
    barrier_to_present.dstAccessMask       = VK_ACCESS_MEMORY_READ_BIT;
    barrier_to_present.oldLayout           = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    barrier_to_present.newLayout           = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
    barrier_to_present.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier_to_present.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier_to_present.image               = swapchain_image;
    barrier_to_present.subresourceRange    = barrier_to_src.subresourceRange;

    dev_disp->CmdPipelineBarrier(cmd_buf,
        VK_PIPELINE_STAGE_TRANSFER_BIT,
        VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,
        0, 0, NULL, 0, NULL, 1, &barrier_to_present);

    dev_disp->EndCommandBuffer(cmd_buf);

    /* Create fence and submit */
    VkFence fence = VK_NULL_HANDLE;
    VkFenceCreateInfo fence_info = {0};
    fence_info.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    dev_disp->CreateFence(device, &fence_info, NULL, &fence);

    VkSubmitInfo submit_info = {0};
    submit_info.sType              = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit_info.commandBufferCount = 1;
    submit_info.pCommandBuffers    = &cmd_buf;

    res = dev_disp->QueueSubmit(queue, 1, &submit_info, fence);
    if (res == VK_SUCCESS) {
        dev_disp->WaitForFences(device, 1, &fence, VK_TRUE, UINT64_MAX);
    } else {
        fprintf(stderr, "[GLA-VK] readback QueueSubmit failed (%d)\n", res);
    }

    dev_disp->DestroyFence(device, fence, NULL);

    /* Map staging memory and copy pixels into SHM slot */
    if (res == VK_SUCCESS) {
        void *mapped = NULL;
        if (dev_disp->MapMemory(device, staging_mem, 0, pixel_bytes, 0, &mapped)
                == VK_SUCCESS && mapped) {
            memcpy(ptr, mapped, (size_t)pixel_bytes);
            dev_disp->UnmapMemory(device, staging_mem);
        }
    }
    ptr += (size_t)pixel_bytes;

    /* Cleanup readback resources */
    dev_disp->FreeCommandBuffers(device, cmd_pool, 1, &cmd_buf);
cleanup_pool:
    dev_disp->DestroyCommandPool(device, cmd_pool, NULL);
cleanup_mem:
    if (staging_mem != VK_NULL_HANDLE)
        dev_disp->FreeMemory(device, staging_mem, NULL);
    if (staging_buf != VK_NULL_HANDLE)
        dev_disp->DestroyBuffer(device, staging_buf, NULL);

write_metadata_only:
    /* Serialise accumulated draw call metadata into the remaining slot space */
    {
        const size_t kDrawCallBudget = 8u * 1024u * 1024u;
        pthread_mutex_lock(&g_frame_mutex);
        size_t written = serialise_vk_draw_calls(ptr, kDrawCallBudget,
                                                  g_frame_draws,
                                                  g_frame_draw_count);
        pthread_mutex_unlock(&g_frame_mutex);
        ptr += written;
    }

    uint64_t total_size = (uint64_t)((uintptr_t)ptr - (uintptr_t)slot);
    gla_vk_ipc_commit_slot(slot_index, total_size);
    gla_vk_ipc_send_frame_ready(g_frame_id, slot_index);

    /* Check for engine pause request */
    if (gla_vk_ipc_should_pause()) {
        gla_vk_ipc_wait_resume();
    }

reset_frame:
    pthread_mutex_lock(&g_frame_mutex);
    g_frame_draw_count = 0;
    g_frame_id++;
    pthread_mutex_unlock(&g_frame_mutex);
}
