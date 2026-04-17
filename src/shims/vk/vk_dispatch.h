#ifndef VK_DISPATCH_H
#define VK_DISPATCH_H

/*
 * vk_dispatch.h — Per-instance and per-device dispatch tables.
 *
 * Each Vulkan object (VkInstance, VkDevice) has a dispatch key as its first
 * member (a pointer-to-pointer used by the loader). We use this key to look
 * up our stored dispatch table in a simple hash table.
 *
 * Dispatch table chaining: each entry holds function pointers pointing to the
 * *next* layer (or the driver) so we can call down the chain.
 */

#include <vulkan/vulkan.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 * Instance dispatch table
 * Subset of instance-level functions we intercept or need to call down.
 * ---------------------------------------------------------------------- */
typedef struct GlaInstanceDispatch {
    /* Dispatch key — must be first: pointer to the loader's dispatch table */
    void *dispatch_key;

    /* Next layer / driver function pointers */
    PFN_vkGetInstanceProcAddr     GetInstanceProcAddr;
    PFN_vkDestroyInstance         DestroyInstance;
    PFN_vkCreateDevice            CreateDevice;

    /* Used internally to enumerate physical devices (for completeness) */
    PFN_vkEnumeratePhysicalDevices EnumeratePhysicalDevices;
} GlaInstanceDispatch;

/* -------------------------------------------------------------------------
 * Device dispatch table
 * Subset of device-level functions we intercept or need to call down.
 * ---------------------------------------------------------------------- */
typedef struct GlaDeviceDispatch {
    /* Dispatch key */
    void *dispatch_key;

    /* Next layer / driver function pointers */
    PFN_vkGetDeviceProcAddr       GetDeviceProcAddr;
    PFN_vkDestroyDevice           DestroyDevice;

    /* Command buffer recording */
    PFN_vkQueueSubmit             QueueSubmit;
    PFN_vkCmdDraw                 CmdDraw;
    PFN_vkCmdDrawIndexed          CmdDrawIndexed;
    PFN_vkCmdBindPipeline         CmdBindPipeline;
    PFN_vkCmdBindDescriptorSets   CmdBindDescriptorSets;
    PFN_vkCmdBeginRenderPass      CmdBeginRenderPass;
    PFN_vkCmdEndRenderPass        CmdEndRenderPass;

    /* Swapchain — frame boundary */
    PFN_vkQueuePresentKHR         QueuePresentKHR;

    /* Image readback helpers */
    PFN_vkCreateFence             CreateFence;
    PFN_vkDestroyFence            DestroyFence;
    PFN_vkWaitForFences           WaitForFences;
    PFN_vkResetFences             ResetFences;
    PFN_vkAllocateCommandBuffers  AllocateCommandBuffers;
    PFN_vkFreeCommandBuffers      FreeCommandBuffers;
    PFN_vkBeginCommandBuffer      BeginCommandBuffer;
    PFN_vkEndCommandBuffer        EndCommandBuffer;
    PFN_vkQueueSubmit             QueueSubmit2;  /* alias, unused */
    PFN_vkCreateBuffer            CreateBuffer;
    PFN_vkDestroyBuffer           DestroyBuffer;
    PFN_vkAllocateMemory          AllocateMemory;
    PFN_vkFreeMemory              FreeMemory;
    PFN_vkBindBufferMemory        BindBufferMemory;
    PFN_vkMapMemory               MapMemory;
    PFN_vkUnmapMemory             UnmapMemory;
    PFN_vkGetBufferMemoryRequirements GetBufferMemoryRequirements;
    PFN_vkGetPhysicalDeviceMemoryProperties2 GetPhysicalDeviceMemoryProperties2; /* unused for now */
    PFN_vkCmdCopyImageToBuffer    CmdCopyImageToBuffer;
    PFN_vkCmdPipelineBarrier      CmdPipelineBarrier;
    PFN_vkCreateCommandPool       CreateCommandPool;
    PFN_vkDestroyCommandPool      DestroyCommandPool;

    /* Physical device handle needed for memory type queries */
    VkPhysicalDevice              physical_device;
} GlaDeviceDispatch;

/* -------------------------------------------------------------------------
 * Registry: store/retrieve dispatch tables keyed by the dispatch pointer.
 * Thread-safe (protected by a mutex).
 * ---------------------------------------------------------------------- */

/* Extract the dispatch key from any dispatchable Vulkan handle */
static inline void *gla_dispatch_key(const void *dispatchable_handle) {
    /* The loader places a pointer to its internal dispatch table as the first
     * word of every dispatchable object. */
    return *(void *const *)dispatchable_handle;
}

void gla_instance_dispatch_store(VkInstance instance, GlaInstanceDispatch *disp);
GlaInstanceDispatch *gla_instance_dispatch_get(VkInstance instance);
void gla_instance_dispatch_remove(VkInstance instance);

void gla_device_dispatch_store(VkDevice device, GlaDeviceDispatch *disp);
GlaDeviceDispatch *gla_device_dispatch_get(VkDevice device);
void gla_device_dispatch_remove(VkDevice device);

void gla_dispatch_init(void);
void gla_dispatch_cleanup(void);

#ifdef __cplusplus
}
#endif

#endif /* VK_DISPATCH_H */
