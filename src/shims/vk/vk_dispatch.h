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
typedef struct GpaInstanceDispatch {
    /* Dispatch key — must be first: pointer to the loader's dispatch table */
    void *dispatch_key;

    /* Cached real handle — needed when chaining down instance-level commands
     * (eg. vkGetPhysicalDeviceSurfaceCapabilitiesKHR) since the next-layer
     * GetInstanceProcAddr returns NULL for them when called with
     * VK_NULL_HANDLE. */
    VkInstance                    instance;

    /* Next layer / driver function pointers */
    PFN_vkGetInstanceProcAddr     GetInstanceProcAddr;
    PFN_vkDestroyInstance         DestroyInstance;
    PFN_vkCreateDevice            CreateDevice;

    /* Used internally to enumerate physical devices (for completeness) */
    PFN_vkEnumeratePhysicalDevices EnumeratePhysicalDevices;

    /* Surface queries — resolved at instance creation time so that chain-down
     * does not have to call our own GetInstanceProcAddr again (which would
     * recurse: the loader's trampoline routes extension-function lookups
     * through every loaded layer including us). */
    PFN_vkDestroySurfaceKHR                       DestroySurfaceKHR;
    PFN_vkGetPhysicalDeviceSurfaceSupportKHR      GetPhysicalDeviceSurfaceSupportKHR;
    PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR GetPhysicalDeviceSurfaceCapabilitiesKHR;
    PFN_vkGetPhysicalDeviceSurfaceFormatsKHR      GetPhysicalDeviceSurfaceFormatsKHR;
    PFN_vkGetPhysicalDeviceSurfacePresentModesKHR GetPhysicalDeviceSurfacePresentModesKHR;
    PFN_vkGetPhysicalDeviceMemoryProperties       GetPhysicalDeviceMemoryProperties;
} GpaInstanceDispatch;

/* -------------------------------------------------------------------------
 * Device dispatch table
 * Subset of device-level functions we intercept or need to call down.
 * ---------------------------------------------------------------------- */
typedef struct GpaDeviceDispatch {
    /* Dispatch key */
    void *dispatch_key;

    /* Next layer / driver function pointers */
    PFN_vkGetDeviceProcAddr       GetDeviceProcAddr;
    PFN_vkDestroyDevice           DestroyDevice;

    /* Command buffer recording */
    PFN_vkQueueSubmit             QueueSubmit;
    PFN_vkQueueSubmit2            QueueSubmit2KHR;  /* used for both _KHR and core 1.3 */
    PFN_vkCmdDraw                 CmdDraw;
    PFN_vkCmdDrawIndexed          CmdDrawIndexed;
    PFN_vkCmdDrawIndirect         CmdDrawIndirect;
    PFN_vkCmdDrawIndexedIndirect  CmdDrawIndexedIndirect;
    PFN_vkCmdDrawIndirectCount    CmdDrawIndirectCount;
    PFN_vkCmdDrawIndexedIndirectCount CmdDrawIndexedIndirectCount;
    PFN_vkCmdBeginRendering       CmdBeginRendering;
    PFN_vkCmdEndRendering         CmdEndRendering;
    PFN_vkCmdBindPipeline         CmdBindPipeline;
    PFN_vkCmdDispatch             CmdDispatch;
    PFN_vkCmdExecuteCommands      CmdExecuteCommands;
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
    /* (older alias slot — left as-is; QueueSubmit2KHR above carries the
     * real vkQueueSubmit2 entrypoint.) */
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

    /* Queue family used by readback path (first family from CreateDevice's
     * pQueueCreateInfos — the same family the app submits its presents on
     * for single-queue apps). Avoids hardcoding family 0, which causes
     * vkQueueSubmit to silently stall on devices where the present queue
     * is a different family (eg. NVIDIA's compute-only queue). */
    uint32_t                      readback_queue_family;
    PFN_vkGetDeviceQueue          GetDeviceQueue;
} GpaDeviceDispatch;

/* -------------------------------------------------------------------------
 * Registry: store/retrieve dispatch tables keyed by the dispatch pointer.
 * Thread-safe (protected by a mutex).
 * ---------------------------------------------------------------------- */

/* Extract the dispatch key from any dispatchable Vulkan handle */
static inline void *gpa_dispatch_key(const void *dispatchable_handle) {
    /* The loader places a pointer to its internal dispatch table as the first
     * word of every dispatchable object. */
    return *(void *const *)dispatchable_handle;
}

void gpa_instance_dispatch_store(VkInstance instance, GpaInstanceDispatch *disp);
GpaInstanceDispatch *gpa_instance_dispatch_get(VkInstance instance);
void gpa_instance_dispatch_remove(VkInstance instance);

void gpa_device_dispatch_store(VkDevice device, GpaDeviceDispatch *disp);
GpaDeviceDispatch *gpa_device_dispatch_get(VkDevice device);
void gpa_device_dispatch_remove(VkDevice device);

void gpa_dispatch_init(void);
void gpa_dispatch_cleanup(void);

#ifdef __cplusplus
}
#endif

#endif /* VK_DISPATCH_H */
