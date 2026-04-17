#define _GNU_SOURCE
#include "gla_layer.h"
#include "vk_dispatch.h"
#include "vk_capture.h"
#include "vk_ipc_client.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* --------------------------------------------------------------------------
 * Swapchain image tracking
 *
 * We need to map (VkSwapchainKHR, image_index) → VkImage so that
 * gla_capture_on_present can pass the actual VkImage handle.
 * -------------------------------------------------------------------------- */

#define MAX_SWAPCHAINS 16
#define MAX_SWAPCHAIN_IMAGES 8

typedef struct {
    VkSwapchainKHR swapchain;
    VkDevice       device;
    VkImage        images[MAX_SWAPCHAIN_IMAGES];
    uint32_t       image_count;
    VkExtent2D     extent;
    VkFormat       format;
} SwapchainInfo;

static SwapchainInfo g_swapchains[MAX_SWAPCHAINS];
static uint32_t      g_swapchain_count = 0;

static SwapchainInfo *find_swapchain(VkSwapchainKHR sc) {
    for (uint32_t i = 0; i < g_swapchain_count; i++) {
        if (g_swapchains[i].swapchain == sc) return &g_swapchains[i];
    }
    return NULL;
}

/* --------------------------------------------------------------------------
 * vkCreateInstance — layer initialisation
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR VkResult VKAPI_CALL
gla_CreateInstance(const VkInstanceCreateInfo  *pCreateInfo,
                   const VkAllocationCallbacks *pAllocator,
                   VkInstance                  *pInstance) {
    /* Walk the pNext chain to find the loader link info */
    VkLayerInstanceCreateInfo *layer_create_info =
        (VkLayerInstanceCreateInfo *)pCreateInfo->pNext;
    while (layer_create_info &&
           !(layer_create_info->sType ==
                 VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO &&
             layer_create_info->function == VK_LAYER_LINK_INFO)) {
        layer_create_info =
            (VkLayerInstanceCreateInfo *)layer_create_info->pNext;
    }
    if (!layer_create_info) return VK_ERROR_INITIALIZATION_FAILED;

    /* Capture the next layer's GetInstanceProcAddr, then advance the chain */
    PFN_vkGetInstanceProcAddr next_gipa =
        layer_create_info->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    layer_create_info->u.pLayerInfo =
        layer_create_info->u.pLayerInfo->pNext;

    /* Call down to create the instance */
    PFN_vkCreateInstance next_create_instance =
        (PFN_vkCreateInstance)next_gipa(VK_NULL_HANDLE, "vkCreateInstance");
    if (!next_create_instance) return VK_ERROR_INITIALIZATION_FAILED;

    VkResult result = next_create_instance(pCreateInfo, pAllocator, pInstance);
    if (result != VK_SUCCESS) return result;

    /* Build and store our instance dispatch table */
    GlaInstanceDispatch disp;
    memset(&disp, 0, sizeof(disp));
    disp.dispatch_key = *(void **)(*pInstance);
    disp.GetInstanceProcAddr =
        (PFN_vkGetInstanceProcAddr)next_gipa(*pInstance,
                                             "vkGetInstanceProcAddr");
    disp.DestroyInstance =
        (PFN_vkDestroyInstance)next_gipa(*pInstance, "vkDestroyInstance");
    disp.CreateDevice =
        (PFN_vkCreateDevice)next_gipa(*pInstance, "vkCreateDevice");
    disp.EnumeratePhysicalDevices =
        (PFN_vkEnumeratePhysicalDevices)next_gipa(*pInstance,
                                                  "vkEnumeratePhysicalDevices");
    gla_instance_dispatch_store(*pInstance, &disp);

    /* Initialise subsystems once */
    static int g_inited = 0;
    if (!g_inited) {
        gla_dispatch_init();
        gla_capture_init();
        gla_vk_ipc_connect();
        g_inited = 1;
    }

    return VK_SUCCESS;
}

/* --------------------------------------------------------------------------
 * vkDestroyInstance
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR void VKAPI_CALL
gla_DestroyInstance(VkInstance                  instance,
                    const VkAllocationCallbacks *pAllocator) {
    GlaInstanceDispatch *disp = gla_instance_dispatch_get(instance);
    if (disp && disp->DestroyInstance)
        disp->DestroyInstance(instance, pAllocator);

    gla_instance_dispatch_remove(instance);
    gla_vk_ipc_disconnect();
    gla_capture_shutdown();
}

/* --------------------------------------------------------------------------
 * vkCreateDevice — per-device state
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR VkResult VKAPI_CALL
gla_CreateDevice(VkPhysicalDevice             physicalDevice,
                 const VkDeviceCreateInfo    *pCreateInfo,
                 const VkAllocationCallbacks *pAllocator,
                 VkDevice                    *pDevice) {
    /* Walk pNext for device link info */
    VkLayerDeviceCreateInfo *layer_create_info =
        (VkLayerDeviceCreateInfo *)pCreateInfo->pNext;
    while (layer_create_info &&
           !(layer_create_info->sType ==
                 VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO &&
             layer_create_info->function == VK_LAYER_LINK_INFO)) {
        layer_create_info =
            (VkLayerDeviceCreateInfo *)layer_create_info->pNext;
    }
    if (!layer_create_info) return VK_ERROR_INITIALIZATION_FAILED;

    PFN_vkGetInstanceProcAddr next_gipa =
        layer_create_info->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr next_gdpa =
        layer_create_info->u.pLayerInfo->pfnNextGetDeviceProcAddr;
    layer_create_info->u.pLayerInfo = layer_create_info->u.pLayerInfo->pNext;

    PFN_vkCreateDevice next_create_device =
        (PFN_vkCreateDevice)next_gipa(VK_NULL_HANDLE, "vkCreateDevice");
    if (!next_create_device) return VK_ERROR_INITIALIZATION_FAILED;

    VkResult result = next_create_device(physicalDevice, pCreateInfo,
                                         pAllocator, pDevice);
    if (result != VK_SUCCESS) return result;

    /* Build device dispatch table */
    GlaDeviceDispatch disp;
    memset(&disp, 0, sizeof(disp));
    disp.dispatch_key     = *(void **)(*pDevice);
    disp.physical_device  = physicalDevice;

#define GDPA(name) (PFN_vk##name)next_gdpa(*pDevice, "vk" #name)
    disp.GetDeviceProcAddr     = GDPA(GetDeviceProcAddr);
    disp.DestroyDevice         = GDPA(DestroyDevice);
    disp.QueueSubmit           = GDPA(QueueSubmit);
    disp.CmdDraw               = GDPA(CmdDraw);
    disp.CmdDrawIndexed        = GDPA(CmdDrawIndexed);
    disp.CmdBindPipeline       = GDPA(CmdBindPipeline);
    disp.CmdBindDescriptorSets = GDPA(CmdBindDescriptorSets);
    disp.CmdBeginRenderPass    = GDPA(CmdBeginRenderPass);
    disp.CmdEndRenderPass      = GDPA(CmdEndRenderPass);
    disp.QueuePresentKHR       = GDPA(QueuePresentKHR);
    disp.CreateFence           = GDPA(CreateFence);
    disp.DestroyFence          = GDPA(DestroyFence);
    disp.WaitForFences         = GDPA(WaitForFences);
    disp.ResetFences           = GDPA(ResetFences);
    disp.AllocateCommandBuffers = GDPA(AllocateCommandBuffers);
    disp.FreeCommandBuffers    = GDPA(FreeCommandBuffers);
    disp.BeginCommandBuffer    = GDPA(BeginCommandBuffer);
    disp.EndCommandBuffer      = GDPA(EndCommandBuffer);
    disp.CreateBuffer          = GDPA(CreateBuffer);
    disp.DestroyBuffer         = GDPA(DestroyBuffer);
    disp.AllocateMemory        = GDPA(AllocateMemory);
    disp.FreeMemory            = GDPA(FreeMemory);
    disp.BindBufferMemory      = GDPA(BindBufferMemory);
    disp.MapMemory             = GDPA(MapMemory);
    disp.UnmapMemory           = GDPA(UnmapMemory);
    disp.GetBufferMemoryRequirements = GDPA(GetBufferMemoryRequirements);
    disp.CmdCopyImageToBuffer  = GDPA(CmdCopyImageToBuffer);
    disp.CmdPipelineBarrier    = GDPA(CmdPipelineBarrier);
    disp.CreateCommandPool     = GDPA(CreateCommandPool);
    disp.DestroyCommandPool    = GDPA(DestroyCommandPool);
#undef GDPA

    gla_device_dispatch_store(*pDevice, &disp);
    return VK_SUCCESS;
}

/* --------------------------------------------------------------------------
 * vkDestroyDevice
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR void VKAPI_CALL
gla_DestroyDevice(VkDevice                     device,
                  const VkAllocationCallbacks *pAllocator) {
    GlaDeviceDispatch *disp = gla_device_dispatch_get(device);
    if (disp && disp->DestroyDevice)
        disp->DestroyDevice(device, pAllocator);
    gla_device_dispatch_remove(device);
}

/* --------------------------------------------------------------------------
 * vkQueueSubmit — harvest draw calls from submitted command buffers
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR VkResult VKAPI_CALL
gla_QueueSubmit(VkQueue             queue,
                uint32_t            submitCount,
                const VkSubmitInfo *pSubmits,
                VkFence             fence) {
    /* Collect draw call metadata from all command buffers before forwarding */
    for (uint32_t s = 0; s < submitCount; s++) {
        const VkSubmitInfo *si = &pSubmits[s];
        gla_capture_queue_submit(si->commandBufferCount,
                                 si->pCommandBuffers);
    }

    /* The queue dispatch key matches the device's key created during
     * vkCreateDevice since the loader sets them both. Look up via the
     * queue's dispatch key by casting to VkDevice (same key). */
    GlaDeviceDispatch *disp = gla_device_dispatch_get((VkDevice)queue);
    if (!disp || !disp->QueueSubmit) return VK_ERROR_DEVICE_LOST;

    return disp->QueueSubmit(queue, submitCount, pSubmits, fence);
}

/* --------------------------------------------------------------------------
 * vkQueuePresentKHR — frame boundary: trigger capture
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR VkResult VKAPI_CALL
gla_QueuePresentKHR(VkQueue                 queue,
                    const VkPresentInfoKHR *pPresentInfo) {
    /* Look up device dispatch — queue shares the same dispatch key */
    GlaDeviceDispatch *dev_disp =
        gla_device_dispatch_get((VkDevice)queue);

    if (dev_disp && gla_vk_ipc_is_connected()) {
        /* Capture each swapchain being presented (usually just one) */
        for (uint32_t i = 0; i < pPresentInfo->swapchainCount; i++) {
            VkSwapchainKHR sc  = pPresentInfo->pSwapchains[i];
            uint32_t       idx = pPresentInfo->pImageIndices[i];

            SwapchainInfo *sc_info = find_swapchain(sc);
            if (sc_info && idx < sc_info->image_count) {
                gla_capture_on_present(
                    queue,
                    sc_info->device,
                    sc,
                    idx,
                    sc_info->images[idx],
                    sc_info->extent,
                    sc_info->format);
            }
        }
    }

    if (!dev_disp || !dev_disp->QueuePresentKHR) return VK_ERROR_DEVICE_LOST;
    return dev_disp->QueuePresentKHR(queue, pPresentInfo);
}

/* --------------------------------------------------------------------------
 * Command buffer recording intercepts
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR void VKAPI_CALL
gla_CmdDraw(VkCommandBuffer commandBuffer,
            uint32_t        vertexCount,
            uint32_t        instanceCount,
            uint32_t        firstVertex,
            uint32_t        firstInstance) {
    gla_capture_record_draw(commandBuffer, vertexCount, instanceCount,
                             firstVertex, firstInstance);

    GlaDeviceDispatch *disp =
        gla_device_dispatch_get((VkDevice)commandBuffer);
    if (disp && disp->CmdDraw)
        disp->CmdDraw(commandBuffer, vertexCount, instanceCount,
                      firstVertex, firstInstance);
}

static VKAPI_ATTR void VKAPI_CALL
gla_CmdDrawIndexed(VkCommandBuffer commandBuffer,
                   uint32_t        indexCount,
                   uint32_t        instanceCount,
                   uint32_t        firstIndex,
                   int32_t         vertexOffset,
                   uint32_t        firstInstance) {
    gla_capture_record_draw_indexed(commandBuffer, indexCount, instanceCount,
                                     firstIndex, vertexOffset, firstInstance);

    GlaDeviceDispatch *disp =
        gla_device_dispatch_get((VkDevice)commandBuffer);
    if (disp && disp->CmdDrawIndexed)
        disp->CmdDrawIndexed(commandBuffer, indexCount, instanceCount,
                             firstIndex, vertexOffset, firstInstance);
}

static VKAPI_ATTR void VKAPI_CALL
gla_CmdBindPipeline(VkCommandBuffer     commandBuffer,
                    VkPipelineBindPoint pipelineBindPoint,
                    VkPipeline          pipeline) {
    gla_capture_bind_pipeline(commandBuffer, pipelineBindPoint, pipeline);

    GlaDeviceDispatch *disp =
        gla_device_dispatch_get((VkDevice)commandBuffer);
    if (disp && disp->CmdBindPipeline)
        disp->CmdBindPipeline(commandBuffer, pipelineBindPoint, pipeline);
}

static VKAPI_ATTR void VKAPI_CALL
gla_CmdBindDescriptorSets(VkCommandBuffer        commandBuffer,
                           VkPipelineBindPoint   pipelineBindPoint,
                           VkPipelineLayout      layout,
                           uint32_t              firstSet,
                           uint32_t              descriptorSetCount,
                           const VkDescriptorSet *pDescriptorSets,
                           uint32_t              dynamicOffsetCount,
                           const uint32_t        *pDynamicOffsets) {
    /* Pass through; no additional metadata captured in M5 MVP */
    GlaDeviceDispatch *disp =
        gla_device_dispatch_get((VkDevice)commandBuffer);
    if (disp && disp->CmdBindDescriptorSets)
        disp->CmdBindDescriptorSets(commandBuffer, pipelineBindPoint, layout,
                                    firstSet, descriptorSetCount,
                                    pDescriptorSets, dynamicOffsetCount,
                                    pDynamicOffsets);
}

static VKAPI_ATTR void VKAPI_CALL
gla_CmdBeginRenderPass(VkCommandBuffer              commandBuffer,
                        const VkRenderPassBeginInfo *pRenderPassBegin,
                        VkSubpassContents            contents) {
    gla_capture_begin_render_pass(commandBuffer);

    GlaDeviceDispatch *disp =
        gla_device_dispatch_get((VkDevice)commandBuffer);
    if (disp && disp->CmdBeginRenderPass)
        disp->CmdBeginRenderPass(commandBuffer, pRenderPassBegin, contents);
}

static VKAPI_ATTR void VKAPI_CALL
gla_CmdEndRenderPass(VkCommandBuffer commandBuffer) {
    gla_capture_end_render_pass(commandBuffer);

    GlaDeviceDispatch *disp =
        gla_device_dispatch_get((VkDevice)commandBuffer);
    if (disp && disp->CmdEndRenderPass)
        disp->CmdEndRenderPass(commandBuffer);
}

/* --------------------------------------------------------------------------
 * Swapchain image enumeration — hook vkGetSwapchainImagesKHR to track images
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR VkResult VKAPI_CALL
gla_GetSwapchainImagesKHR(VkDevice       device,
                           VkSwapchainKHR swapchain,
                           uint32_t      *pSwapchainImageCount,
                           VkImage       *pSwapchainImages) {
    GlaDeviceDispatch *disp = gla_device_dispatch_get(device);
    if (!disp) return VK_ERROR_DEVICE_LOST;

    /* Resolve GetSwapchainImagesKHR from the next layer */
    PFN_vkGetSwapchainImagesKHR next_fn =
        (PFN_vkGetSwapchainImagesKHR)
        disp->GetDeviceProcAddr(device, "vkGetSwapchainImagesKHR");
    if (!next_fn) return VK_ERROR_EXTENSION_NOT_PRESENT;

    VkResult res = next_fn(device, swapchain, pSwapchainImageCount,
                           pSwapchainImages);

    /* On the second call (pSwapchainImages != NULL) store the image list */
    if (res == VK_SUCCESS && pSwapchainImages && *pSwapchainImageCount > 0) {
        SwapchainInfo *sc_info = find_swapchain(swapchain);
        if (!sc_info && g_swapchain_count < MAX_SWAPCHAINS) {
            sc_info = &g_swapchains[g_swapchain_count++];
            memset(sc_info, 0, sizeof(*sc_info));
            sc_info->swapchain = swapchain;
            sc_info->device    = device;
        }
        if (sc_info) {
            uint32_t count = *pSwapchainImageCount;
            if (count > MAX_SWAPCHAIN_IMAGES) count = MAX_SWAPCHAIN_IMAGES;
            sc_info->image_count = count;
            for (uint32_t i = 0; i < count; i++)
                sc_info->images[i] = pSwapchainImages[i];
        }
    }
    return res;
}

/* --------------------------------------------------------------------------
 * vkCreateSwapchainKHR — capture extent + format
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR VkResult VKAPI_CALL
gla_CreateSwapchainKHR(VkDevice                        device,
                        const VkSwapchainCreateInfoKHR *pCreateInfo,
                        const VkAllocationCallbacks    *pAllocator,
                        VkSwapchainKHR                 *pSwapchain) {
    GlaDeviceDispatch *disp = gla_device_dispatch_get(device);
    if (!disp) return VK_ERROR_DEVICE_LOST;

    PFN_vkCreateSwapchainKHR next_fn =
        (PFN_vkCreateSwapchainKHR)
        disp->GetDeviceProcAddr(device, "vkCreateSwapchainKHR");
    if (!next_fn) return VK_ERROR_EXTENSION_NOT_PRESENT;

    VkResult res = next_fn(device, pCreateInfo, pAllocator, pSwapchain);
    if (res == VK_SUCCESS && pCreateInfo && pSwapchain) {
        /* Register swapchain entry with extent + format */
        if (g_swapchain_count < MAX_SWAPCHAINS) {
            SwapchainInfo *sc_info = find_swapchain(*pSwapchain);
            if (!sc_info) {
                sc_info = &g_swapchains[g_swapchain_count++];
                memset(sc_info, 0, sizeof(*sc_info));
            }
            sc_info->swapchain = *pSwapchain;
            sc_info->device    = device;
            sc_info->extent    = pCreateInfo->imageExtent;
            sc_info->format    = pCreateInfo->imageFormat;
        }
    }
    return res;
}

/* --------------------------------------------------------------------------
 * vkDestroySwapchainKHR — clean up tracking entry
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR void VKAPI_CALL
gla_DestroySwapchainKHR(VkDevice                     device,
                          VkSwapchainKHR               swapchain,
                          const VkAllocationCallbacks *pAllocator) {
    /* Remove from our tracking table */
    for (uint32_t i = 0; i < g_swapchain_count; i++) {
        if (g_swapchains[i].swapchain == swapchain) {
            g_swapchains[i] = g_swapchains[--g_swapchain_count];
            break;
        }
    }

    GlaDeviceDispatch *disp = gla_device_dispatch_get(device);
    if (disp) {
        PFN_vkDestroySwapchainKHR next_fn =
            (PFN_vkDestroySwapchainKHR)
            disp->GetDeviceProcAddr(device, "vkDestroySwapchainKHR");
        if (next_fn) next_fn(device, swapchain, pAllocator);
    }
}

/* --------------------------------------------------------------------------
 * vkGetDeviceProcAddr — return our intercepts or chain down
 * -------------------------------------------------------------------------- */

VK_LAYER_EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
gla_vkGetDeviceProcAddr(VkDevice device, const char *pName) {
#define INTERCEPT(fn) \
    if (strcmp(pName, "vk" #fn) == 0) return (PFN_vkVoidFunction)gla_##fn

    if (strcmp(pName, "vkGetDeviceProcAddr") == 0)
        return (PFN_vkVoidFunction)gla_vkGetDeviceProcAddr;
    INTERCEPT(DestroyDevice);
    INTERCEPT(QueueSubmit);
    INTERCEPT(QueuePresentKHR);
    INTERCEPT(CmdDraw);
    INTERCEPT(CmdDrawIndexed);
    INTERCEPT(CmdBindPipeline);
    INTERCEPT(CmdBindDescriptorSets);
    INTERCEPT(CmdBeginRenderPass);
    INTERCEPT(CmdEndRenderPass);
    INTERCEPT(CreateSwapchainKHR);
    INTERCEPT(DestroySwapchainKHR);
    INTERCEPT(GetSwapchainImagesKHR);
#undef INTERCEPT

    GlaDeviceDispatch *disp = gla_device_dispatch_get(device);
    if (disp && disp->GetDeviceProcAddr)
        return disp->GetDeviceProcAddr(device, pName);
    return NULL;
}

/* --------------------------------------------------------------------------
 * vkGetInstanceProcAddr — return our intercepts or chain down
 * -------------------------------------------------------------------------- */

VK_LAYER_EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
gla_vkGetInstanceProcAddr(VkInstance instance, const char *pName) {
    /* Layer negotiation */
    if (strcmp(pName, "vkNegotiateLoaderLayerInterfaceVersion") == 0)
        return (PFN_vkVoidFunction)vkNegotiateLoaderLayerInterfaceVersion;

    /* Instance-level intercepts */
#define INTERCEPT(fn) \
    if (strcmp(pName, "vk" #fn) == 0) return (PFN_vkVoidFunction)gla_##fn

    if (strcmp(pName, "vkGetInstanceProcAddr") == 0)
        return (PFN_vkVoidFunction)gla_vkGetInstanceProcAddr;
    INTERCEPT(CreateInstance);
    INTERCEPT(DestroyInstance);
    INTERCEPT(CreateDevice);
#undef INTERCEPT

    /* Device-level functions also queryable via GetInstanceProcAddr */
    PFN_vkVoidFunction dev_fn = gla_vkGetDeviceProcAddr(VK_NULL_HANDLE, pName);
    if (dev_fn) return dev_fn;

    /* Chain to the next layer */
    if (instance == VK_NULL_HANDLE) return NULL;
    GlaInstanceDispatch *disp = gla_instance_dispatch_get(instance);
    if (disp && disp->GetInstanceProcAddr)
        return disp->GetInstanceProcAddr(instance, pName);
    return NULL;
}

/* --------------------------------------------------------------------------
 * vkNegotiateLoaderLayerInterfaceVersion — required by the loader
 * -------------------------------------------------------------------------- */

VK_LAYER_EXPORT VKAPI_ATTR VkResult VKAPI_CALL
vkNegotiateLoaderLayerInterfaceVersion(VkNegotiateLayerInterface *pVersionStruct) {
    if (pVersionStruct == NULL ||
        pVersionStruct->sType != LAYER_NEGOTIATE_INTERFACE_STRUCT) {
        return VK_ERROR_INITIALIZATION_FAILED;
    }

    if (pVersionStruct->loaderLayerInterfaceVersion >
            CURRENT_LOADER_LAYER_INTERFACE_VERSION) {
        pVersionStruct->loaderLayerInterfaceVersion =
            CURRENT_LOADER_LAYER_INTERFACE_VERSION;
    }

    if (pVersionStruct->loaderLayerInterfaceVersion >= 2) {
        pVersionStruct->pfnGetInstanceProcAddr = gla_vkGetInstanceProcAddr;
        pVersionStruct->pfnGetDeviceProcAddr   = gla_vkGetDeviceProcAddr;
        pVersionStruct->pfnGetPhysicalDeviceProcAddr = NULL;
    }

    return VK_SUCCESS;
}
