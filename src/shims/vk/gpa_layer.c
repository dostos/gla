#define _GNU_SOURCE
#include "gpa_layer.h"
#include "vk_dispatch.h"
#include "vk_capture.h"
#include "vk_ipc_client.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <stdint.h>

/* --------------------------------------------------------------------------
 * Swapchain image tracking
 *
 * We need to map (VkSwapchainKHR, image_index) → VkImage so that
 * gpa_capture_on_present can pass the actual VkImage handle.
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
 * Headless surface + swapchain emulation
 *
 * When chromium (or any other Vulkan client) requests
 * VK_EXT_headless_surface and no underlying ICD supports it, we synthesize
 * the entire surface + swapchain stack in-layer:
 *   - vkCreateHeadlessSurfaceEXT      → return a handle pointing into our registry
 *   - vkDestroySurfaceKHR              → free if ours, else chain
 *   - vkGetPhysicalDeviceSurface{Support,Capabilities,Formats,PresentModes}KHR
 *                                      → synthetic responses for our surfaces
 *   - vkCreateSwapchainKHR             → if surface is ours, allocate real
 *                                        VkImage objects (with backing memory)
 *                                        ourselves and wrap them in a
 *                                        synthetic VkSwapchainKHR handle
 *   - vkDestroySwapchainKHR / vkGetSwapchainImagesKHR / vkAcquireNextImageKHR /
 *     vkQueuePresentKHR                → operate on our registry; capture frame
 *                                        on present.
 *
 * Non-our surfaces / swapchains chain down to the next layer / driver
 * unchanged.
 * -------------------------------------------------------------------------- */

#define GPA_HEADLESS_MAGIC      0x47504148u  /* 'GPAH' */
#define GPA_HEADLESS_SC_MAGIC   0x47504153u  /* 'GPAS' */
#define GPA_MAX_HEADLESS_SURFACES   8
#define GPA_MAX_HEADLESS_SWAPCHAINS 8
#define GPA_MAX_HEADLESS_IMAGES     4

typedef struct {
    uint32_t   magic;
    int        in_use;
    VkInstance instance;
} GpaHeadlessSurface;

typedef struct {
    uint32_t       magic;
    int            in_use;
    VkDevice       device;
    GpaHeadlessSurface *surface;
    VkFormat       format;
    VkExtent2D     extent;
    uint32_t       image_count;
    VkImage        images[GPA_MAX_HEADLESS_IMAGES];
    VkDeviceMemory memories[GPA_MAX_HEADLESS_IMAGES];
    uint32_t       next_acquire;
} GpaHeadlessSwapchain;

static GpaHeadlessSurface   g_h_surfaces[GPA_MAX_HEADLESS_SURFACES];
static GpaHeadlessSwapchain g_h_swapchains[GPA_MAX_HEADLESS_SWAPCHAINS];
static pthread_mutex_t      g_headless_mutex = PTHREAD_MUTEX_INITIALIZER;

static GpaHeadlessSurface *find_headless_surface(VkSurfaceKHR sfc) {
    for (int i = 0; i < GPA_MAX_HEADLESS_SURFACES; i++) {
        GpaHeadlessSurface *s = &g_h_surfaces[i];
        if (s->in_use && s->magic == GPA_HEADLESS_MAGIC &&
            (VkSurfaceKHR)(uintptr_t)s == sfc)
            return s;
    }
    return NULL;
}

static GpaHeadlessSwapchain *find_headless_swapchain(VkSwapchainKHR sc) {
    for (int i = 0; i < GPA_MAX_HEADLESS_SWAPCHAINS; i++) {
        GpaHeadlessSwapchain *s = &g_h_swapchains[i];
        if (s->in_use && s->magic == GPA_HEADLESS_SC_MAGIC &&
            (VkSwapchainKHR)(uintptr_t)s == sc)
            return s;
    }
    return NULL;
}

/* --------------------------------------------------------------------------
 * vkCreateInstance — layer initialisation
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR VkResult VKAPI_CALL
gpa_CreateInstance(const VkInstanceCreateInfo  *pCreateInfo,
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

    /* Build and store our instance dispatch table.
     *
     * We store `next_gipa` itself — NOT `next_gipa(instance, "vkGetInstanceProcAddr")`.
     * The latter returns a loader-level resolver that re-enters our layer when
     * asked for instance-level functions (vkGetPhysicalDeviceSurface*KHR), which
     * causes infinite recursion. `next_gipa` is the next-layer-down GIPA passed
     * to us via VkLayerInstanceCreateInfo and dispatches directly below us. */
    GpaInstanceDispatch disp;
    memset(&disp, 0, sizeof(disp));
    disp.dispatch_key = *(void **)(*pInstance);
    disp.instance     = *pInstance;
    disp.GetInstanceProcAddr = next_gipa;
    disp.DestroyInstance =
        (PFN_vkDestroyInstance)next_gipa(*pInstance, "vkDestroyInstance");
    disp.CreateDevice =
        (PFN_vkCreateDevice)next_gipa(*pInstance, "vkCreateDevice");
    disp.EnumeratePhysicalDevices =
        (PFN_vkEnumeratePhysicalDevices)next_gipa(*pInstance,
                                                  "vkEnumeratePhysicalDevices");
    /* Resolve surface queries here once so we can chain down without going
     * through our own GIPA (which would recurse — the loader trampoline
     * dispatches extension-function lookups through every layer). */
    disp.DestroySurfaceKHR = (PFN_vkDestroySurfaceKHR)
        next_gipa(*pInstance, "vkDestroySurfaceKHR");
    disp.GetPhysicalDeviceSurfaceSupportKHR =
        (PFN_vkGetPhysicalDeviceSurfaceSupportKHR)
        next_gipa(*pInstance, "vkGetPhysicalDeviceSurfaceSupportKHR");
    disp.GetPhysicalDeviceSurfaceCapabilitiesKHR =
        (PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR)
        next_gipa(*pInstance, "vkGetPhysicalDeviceSurfaceCapabilitiesKHR");
    disp.GetPhysicalDeviceSurfaceFormatsKHR =
        (PFN_vkGetPhysicalDeviceSurfaceFormatsKHR)
        next_gipa(*pInstance, "vkGetPhysicalDeviceSurfaceFormatsKHR");
    disp.GetPhysicalDeviceSurfacePresentModesKHR =
        (PFN_vkGetPhysicalDeviceSurfacePresentModesKHR)
        next_gipa(*pInstance, "vkGetPhysicalDeviceSurfacePresentModesKHR");
    disp.GetPhysicalDeviceMemoryProperties =
        (PFN_vkGetPhysicalDeviceMemoryProperties)
        next_gipa(*pInstance, "vkGetPhysicalDeviceMemoryProperties");
    /* Initialise subsystems once — must happen BEFORE storing the dispatch
     * table, because gpa_dispatch_init() zeroes the table. */
    static int g_inited = 0;
    if (!g_inited) {
        gpa_dispatch_init();
        gpa_capture_init();
        gpa_vk_ipc_connect();
        g_inited = 1;
    }

    gpa_instance_dispatch_store(*pInstance, &disp);

    return VK_SUCCESS;
}

/* --------------------------------------------------------------------------
 * vkEnumeratePhysicalDevices — passthrough intercept (required so that
 * the Vulkan loader and other layers can resolve this via our
 * vkGetInstanceProcAddr without getting NULL back)
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR VkResult VKAPI_CALL
gpa_EnumeratePhysicalDevices(VkInstance        instance,
                              uint32_t         *pPhysicalDeviceCount,
                              VkPhysicalDevice *pPhysicalDevices) {
    GpaInstanceDispatch *disp = gpa_instance_dispatch_get(instance);
    if (!disp || !disp->EnumeratePhysicalDevices)
        return VK_ERROR_INITIALIZATION_FAILED;
    return disp->EnumeratePhysicalDevices(instance, pPhysicalDeviceCount,
                                          pPhysicalDevices);
}

/* --------------------------------------------------------------------------
 * vkDestroyInstance
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR void VKAPI_CALL
gpa_DestroyInstance(VkInstance                  instance,
                    const VkAllocationCallbacks *pAllocator) {
    GpaInstanceDispatch *disp = gpa_instance_dispatch_get(instance);
    if (disp && disp->DestroyInstance)
        disp->DestroyInstance(instance, pAllocator);

    gpa_instance_dispatch_remove(instance);
    gpa_vk_ipc_disconnect();
    gpa_capture_shutdown();
}

/* --------------------------------------------------------------------------
 * vkCreateDevice — per-device state
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR VkResult VKAPI_CALL
gpa_CreateDevice(VkPhysicalDevice             physicalDevice,
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
    GpaDeviceDispatch disp;
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
    disp.GetDeviceQueue        = GDPA(GetDeviceQueue);
#undef GDPA

    /* Record the queue family the app used so the readback path can submit
     * to a queue from the same family (instead of guessing family 0, which
     * is wrong on multi-queue-family devices like NVIDIA where compute and
     * graphics live in different families). */
    disp.readback_queue_family = 0;
    if (pCreateInfo->queueCreateInfoCount > 0)
        disp.readback_queue_family =
            pCreateInfo->pQueueCreateInfos[0].queueFamilyIndex;

    gpa_device_dispatch_store(*pDevice, &disp);
    return VK_SUCCESS;
}

/* --------------------------------------------------------------------------
 * vkDestroyDevice
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR void VKAPI_CALL
gpa_DestroyDevice(VkDevice                     device,
                  const VkAllocationCallbacks *pAllocator) {
    GpaDeviceDispatch *disp = gpa_device_dispatch_get(device);
    if (disp && disp->DestroyDevice)
        disp->DestroyDevice(device, pAllocator);
    gpa_device_dispatch_remove(device);
}

/* --------------------------------------------------------------------------
 * vkQueueSubmit — harvest draw calls from submitted command buffers
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR VkResult VKAPI_CALL
gpa_QueueSubmit(VkQueue             queue,
                uint32_t            submitCount,
                const VkSubmitInfo *pSubmits,
                VkFence             fence) {
    /* Collect draw call metadata from all command buffers before forwarding */
    for (uint32_t s = 0; s < submitCount; s++) {
        const VkSubmitInfo *si = &pSubmits[s];
        gpa_capture_queue_submit(si->commandBufferCount,
                                 si->pCommandBuffers);
    }

    /* The queue dispatch key matches the device's key created during
     * vkCreateDevice since the loader sets them both. Look up via the
     * queue's dispatch key by casting to VkDevice (same key). */
    GpaDeviceDispatch *disp = gpa_device_dispatch_get((VkDevice)queue);
    if (!disp || !disp->QueueSubmit) return VK_ERROR_DEVICE_LOST;

    return disp->QueueSubmit(queue, submitCount, pSubmits, fence);
}

/* --------------------------------------------------------------------------
 * vkQueuePresentKHR — frame boundary: trigger capture
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR VkResult VKAPI_CALL
gpa_QueuePresentKHR(VkQueue                 queue,
                    const VkPresentInfoKHR *pPresentInfo) {
    /* Look up device dispatch — queue shares the same dispatch key */
    GpaDeviceDispatch *dev_disp =
        gpa_device_dispatch_get((VkDevice)queue);

    /* Detect whether ALL presented swapchains are headless. If so we must
     * NOT chain to the driver's QueuePresentKHR (it'd reject the synthetic
     * VkSwapchainKHR handles). */
    int all_headless = pPresentInfo->swapchainCount > 0;
    int any_headless = 0;
    int per_sc_headless[16] = {0};
    for (uint32_t i = 0; i < pPresentInfo->swapchainCount && i < 16; i++) {
        pthread_mutex_lock(&g_headless_mutex);
        int is_headless = find_headless_swapchain(pPresentInfo->pSwapchains[i]) != NULL;
        pthread_mutex_unlock(&g_headless_mutex);
        per_sc_headless[i] = is_headless;
        if (is_headless) any_headless = 1;
        else all_headless = 0;
    }

    if (dev_disp && gpa_vk_ipc_is_connected()) {
        /* Capture each swapchain being presented (usually just one) */
        for (uint32_t i = 0; i < pPresentInfo->swapchainCount; i++) {
            VkSwapchainKHR sc  = pPresentInfo->pSwapchains[i];
            uint32_t       idx = pPresentInfo->pImageIndices[i];

            SwapchainInfo *sc_info = find_swapchain(sc);
            if (sc_info && idx < sc_info->image_count) {
                gpa_capture_on_present(
                    queue,
                    sc_info->device,
                    sc,
                    idx,
                    sc_info->images[idx],
                    sc_info->extent,
                    sc_info->format,
                    /*skip_pixel_readback=*/(i < 16) ? per_sc_headless[i] : 0);
            }
        }
    }

    if (all_headless) return VK_SUCCESS;
    if (any_headless) {
        /* Mixed present (rare): set per-swapchain results and chain only
         * the non-headless ones is non-trivial; just return success here.
         * Real apps won't mix kinds. */
        return VK_SUCCESS;
    }
    if (!dev_disp || !dev_disp->QueuePresentKHR) return VK_ERROR_DEVICE_LOST;
    return dev_disp->QueuePresentKHR(queue, pPresentInfo);
}

/* --------------------------------------------------------------------------
 * Command buffer recording intercepts
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR void VKAPI_CALL
gpa_CmdDraw(VkCommandBuffer commandBuffer,
            uint32_t        vertexCount,
            uint32_t        instanceCount,
            uint32_t        firstVertex,
            uint32_t        firstInstance) {
    gpa_capture_record_draw(commandBuffer, vertexCount, instanceCount,
                             firstVertex, firstInstance);

    GpaDeviceDispatch *disp =
        gpa_device_dispatch_get((VkDevice)commandBuffer);
    if (disp && disp->CmdDraw)
        disp->CmdDraw(commandBuffer, vertexCount, instanceCount,
                      firstVertex, firstInstance);
}

static VKAPI_ATTR void VKAPI_CALL
gpa_CmdDrawIndexed(VkCommandBuffer commandBuffer,
                   uint32_t        indexCount,
                   uint32_t        instanceCount,
                   uint32_t        firstIndex,
                   int32_t         vertexOffset,
                   uint32_t        firstInstance) {
    gpa_capture_record_draw_indexed(commandBuffer, indexCount, instanceCount,
                                     firstIndex, vertexOffset, firstInstance);

    GpaDeviceDispatch *disp =
        gpa_device_dispatch_get((VkDevice)commandBuffer);
    if (disp && disp->CmdDrawIndexed)
        disp->CmdDrawIndexed(commandBuffer, indexCount, instanceCount,
                             firstIndex, vertexOffset, firstInstance);
}

static VKAPI_ATTR void VKAPI_CALL
gpa_CmdBindPipeline(VkCommandBuffer     commandBuffer,
                    VkPipelineBindPoint pipelineBindPoint,
                    VkPipeline          pipeline) {
    gpa_capture_bind_pipeline(commandBuffer, pipelineBindPoint, pipeline);

    GpaDeviceDispatch *disp =
        gpa_device_dispatch_get((VkDevice)commandBuffer);
    if (disp && disp->CmdBindPipeline)
        disp->CmdBindPipeline(commandBuffer, pipelineBindPoint, pipeline);
}

static VKAPI_ATTR void VKAPI_CALL
gpa_CmdBindDescriptorSets(VkCommandBuffer        commandBuffer,
                           VkPipelineBindPoint   pipelineBindPoint,
                           VkPipelineLayout      layout,
                           uint32_t              firstSet,
                           uint32_t              descriptorSetCount,
                           const VkDescriptorSet *pDescriptorSets,
                           uint32_t              dynamicOffsetCount,
                           const uint32_t        *pDynamicOffsets) {
    /* Pass through; no additional metadata captured in M5 MVP */
    GpaDeviceDispatch *disp =
        gpa_device_dispatch_get((VkDevice)commandBuffer);
    if (disp && disp->CmdBindDescriptorSets)
        disp->CmdBindDescriptorSets(commandBuffer, pipelineBindPoint, layout,
                                    firstSet, descriptorSetCount,
                                    pDescriptorSets, dynamicOffsetCount,
                                    pDynamicOffsets);
}

static VKAPI_ATTR void VKAPI_CALL
gpa_CmdBeginRenderPass(VkCommandBuffer              commandBuffer,
                        const VkRenderPassBeginInfo *pRenderPassBegin,
                        VkSubpassContents            contents) {
    gpa_capture_begin_render_pass(commandBuffer);

    GpaDeviceDispatch *disp =
        gpa_device_dispatch_get((VkDevice)commandBuffer);
    if (disp && disp->CmdBeginRenderPass)
        disp->CmdBeginRenderPass(commandBuffer, pRenderPassBegin, contents);
}

static VKAPI_ATTR void VKAPI_CALL
gpa_CmdEndRenderPass(VkCommandBuffer commandBuffer) {
    gpa_capture_end_render_pass(commandBuffer);

    GpaDeviceDispatch *disp =
        gpa_device_dispatch_get((VkDevice)commandBuffer);
    if (disp && disp->CmdEndRenderPass)
        disp->CmdEndRenderPass(commandBuffer);
}

/* --------------------------------------------------------------------------
 * Swapchain image enumeration — hook vkGetSwapchainImagesKHR to track images
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR VkResult VKAPI_CALL
gpa_GetSwapchainImagesKHR(VkDevice       device,
                           VkSwapchainKHR swapchain,
                           uint32_t      *pSwapchainImageCount,
                           VkImage       *pSwapchainImages) {
    /* Headless? Return our images. */
    pthread_mutex_lock(&g_headless_mutex);
    GpaHeadlessSwapchain *hsc = find_headless_swapchain(swapchain);
    if (hsc) {
        if (!pSwapchainImages) {
            *pSwapchainImageCount = hsc->image_count;
            pthread_mutex_unlock(&g_headless_mutex);
            return VK_SUCCESS;
        }
        uint32_t copy = (*pSwapchainImageCount < hsc->image_count) ?
                        *pSwapchainImageCount : hsc->image_count;
        for (uint32_t i = 0; i < copy; i++) pSwapchainImages[i] = hsc->images[i];
        *pSwapchainImageCount = copy;
        VkResult r = (copy < hsc->image_count) ? VK_INCOMPLETE : VK_SUCCESS;
        pthread_mutex_unlock(&g_headless_mutex);
        return r;
    }
    pthread_mutex_unlock(&g_headless_mutex);

    GpaDeviceDispatch *disp = gpa_device_dispatch_get(device);
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
gpa_CreateSwapchainKHR(VkDevice                        device,
                        const VkSwapchainCreateInfoKHR *pCreateInfo,
                        const VkAllocationCallbacks    *pAllocator,
                        VkSwapchainKHR                 *pSwapchain) {
    GpaDeviceDispatch *disp = gpa_device_dispatch_get(device);
    if (!disp) return VK_ERROR_DEVICE_LOST;

    /* Headless surface? Emulate the swapchain ourselves. */
    pthread_mutex_lock(&g_headless_mutex);
    GpaHeadlessSurface *hsfc = find_headless_surface(pCreateInfo->surface);
    pthread_mutex_unlock(&g_headless_mutex);
    if (hsfc) {
        pthread_mutex_lock(&g_headless_mutex);
        GpaHeadlessSwapchain *slot = NULL;
        for (int i = 0; i < GPA_MAX_HEADLESS_SWAPCHAINS; i++) {
            if (!g_h_swapchains[i].in_use) { slot = &g_h_swapchains[i]; break; }
        }
        if (!slot) {
            pthread_mutex_unlock(&g_headless_mutex);
            return VK_ERROR_OUT_OF_HOST_MEMORY;
        }
        memset(slot, 0, sizeof(*slot));
        slot->magic   = GPA_HEADLESS_SC_MAGIC;
        slot->in_use  = 1;
        slot->device  = device;
        slot->surface = hsfc;
        slot->format  = pCreateInfo->imageFormat;
        slot->extent  = pCreateInfo->imageExtent;
        slot->image_count = pCreateInfo->minImageCount;
        if (slot->image_count < 2) slot->image_count = 2;
        if (slot->image_count > GPA_MAX_HEADLESS_IMAGES) slot->image_count = GPA_MAX_HEADLESS_IMAGES;
        pthread_mutex_unlock(&g_headless_mutex);

        /* Resolve image management functions lazily */
        PFN_vkCreateImage create_image = (PFN_vkCreateImage)
            disp->GetDeviceProcAddr(device, "vkCreateImage");
        PFN_vkGetImageMemoryRequirements get_reqs = (PFN_vkGetImageMemoryRequirements)
            disp->GetDeviceProcAddr(device, "vkGetImageMemoryRequirements");
        PFN_vkBindImageMemory bind_mem = (PFN_vkBindImageMemory)
            disp->GetDeviceProcAddr(device, "vkBindImageMemory");
        if (!create_image || !get_reqs || !bind_mem ||
            !disp->AllocateMemory || !disp->FreeMemory) {
            slot->in_use = 0;
            return VK_ERROR_INITIALIZATION_FAILED;
        }

        /* Get memory properties via instance dispatch (physical_device shares
         * dispatch_key with its instance — we cached the function at
         * CreateInstance to avoid the recursion the loader trampoline causes
         * when intercepted instance-level lookups go through us again). */
        VkPhysicalDeviceMemoryProperties mem_props = {0};
        if (disp->physical_device != VK_NULL_HANDLE) {
            GpaInstanceDispatch *idisp =
                gpa_instance_dispatch_get((VkInstance)disp->physical_device);
            if (idisp && idisp->GetPhysicalDeviceMemoryProperties)
                idisp->GetPhysicalDeviceMemoryProperties(disp->physical_device,
                                                           &mem_props);
        }

        VkImageCreateInfo ici = {0};
        ici.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
        ici.imageType = VK_IMAGE_TYPE_2D;
        ici.format = pCreateInfo->imageFormat;
        ici.extent.width  = pCreateInfo->imageExtent.width;
        ici.extent.height = pCreateInfo->imageExtent.height;
        ici.extent.depth  = 1;
        ici.mipLevels = 1;
        ici.arrayLayers = 1;
        ici.samples = VK_SAMPLE_COUNT_1_BIT;
        ici.tiling = VK_IMAGE_TILING_OPTIMAL;
        /* Force TRANSFER_SRC so our readback path can copy these images, in
         * addition to whatever the app requested. */
        ici.usage = pCreateInfo->imageUsage | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
        ici.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        ici.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;

        for (uint32_t i = 0; i < slot->image_count; i++) {
            if (create_image(device, &ici, NULL, &slot->images[i]) != VK_SUCCESS) {
                slot->in_use = 0;
                return VK_ERROR_OUT_OF_DEVICE_MEMORY;
            }
            VkMemoryRequirements req = {0};
            get_reqs(device, slot->images[i], &req);

            int32_t mem_type = -1;
            for (uint32_t t = 0; t < mem_props.memoryTypeCount; t++) {
                if ((req.memoryTypeBits & (1u << t)) &&
                    (mem_props.memoryTypes[t].propertyFlags &
                     VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)) {
                    mem_type = (int32_t)t;
                    break;
                }
            }
            if (mem_type < 0) {
                slot->in_use = 0;
                return VK_ERROR_OUT_OF_DEVICE_MEMORY;
            }
            VkMemoryAllocateInfo mai = {0};
            mai.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
            mai.allocationSize  = req.size;
            mai.memoryTypeIndex = (uint32_t)mem_type;
            if (disp->AllocateMemory(device, &mai, NULL, &slot->memories[i]) != VK_SUCCESS) {
                slot->in_use = 0;
                return VK_ERROR_OUT_OF_DEVICE_MEMORY;
            }
            bind_mem(device, slot->images[i], slot->memories[i], 0);
        }

        *pSwapchain = (VkSwapchainKHR)(uintptr_t)slot;
        fprintf(stderr,
                "[OpenGPA-VK] emulated headless swapchain %p (%ux%u, %u images)\n",
                (void*)slot, slot->extent.width, slot->extent.height,
                slot->image_count);

        /* Also register in legacy SwapchainInfo so QueuePresent capture path
         * can find extent/format. */
        if (g_swapchain_count < MAX_SWAPCHAINS) {
            SwapchainInfo *sc_info = &g_swapchains[g_swapchain_count++];
            memset(sc_info, 0, sizeof(*sc_info));
            sc_info->swapchain = *pSwapchain;
            sc_info->device    = device;
            sc_info->extent    = slot->extent;
            sc_info->format    = slot->format;
            sc_info->image_count = slot->image_count;
            for (uint32_t i = 0; i < slot->image_count; i++)
                sc_info->images[i] = slot->images[i];
        }
        return VK_SUCCESS;
    }

    /* Real surface — chain down to the driver */
    PFN_vkCreateSwapchainKHR next_fn =
        (PFN_vkCreateSwapchainKHR)
        disp->GetDeviceProcAddr(device, "vkCreateSwapchainKHR");
    if (!next_fn) return VK_ERROR_EXTENSION_NOT_PRESENT;

    VkResult res = next_fn(device, pCreateInfo, pAllocator, pSwapchain);
    if (res == VK_SUCCESS && pCreateInfo && pSwapchain) {
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

/* vkAcquireNextImageKHR — for headless swapchains, rotate through our
 * preallocated images. For real swapchains, chain down. */
static VKAPI_ATTR VkResult VKAPI_CALL
gpa_AcquireNextImageKHR(VkDevice device, VkSwapchainKHR swapchain,
                         uint64_t timeout, VkSemaphore semaphore,
                         VkFence fence, uint32_t *pImageIndex) {
    pthread_mutex_lock(&g_headless_mutex);
    GpaHeadlessSwapchain *hsc = find_headless_swapchain(swapchain);
    if (hsc) {
        *pImageIndex = hsc->next_acquire % hsc->image_count;
        hsc->next_acquire++;
        pthread_mutex_unlock(&g_headless_mutex);
        /* Without a real present, semaphore/fence signaling is the user's
         * responsibility upstream — chromium handles its own synchronisation
         * around image acquire. We return success immediately. */
        (void)timeout; (void)semaphore; (void)fence;
        return VK_SUCCESS;
    }
    pthread_mutex_unlock(&g_headless_mutex);
    GpaDeviceDispatch *disp = gpa_device_dispatch_get(device);
    if (!disp) return VK_ERROR_DEVICE_LOST;
    PFN_vkAcquireNextImageKHR next_fn = (PFN_vkAcquireNextImageKHR)
        disp->GetDeviceProcAddr(device, "vkAcquireNextImageKHR");
    if (!next_fn) return VK_ERROR_EXTENSION_NOT_PRESENT;
    return next_fn(device, swapchain, timeout, semaphore, fence, pImageIndex);
}

/* --------------------------------------------------------------------------
 * vkDestroySwapchainKHR — clean up tracking entry
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR void VKAPI_CALL
gpa_DestroySwapchainKHR(VkDevice                     device,
                          VkSwapchainKHR               swapchain,
                          const VkAllocationCallbacks *pAllocator) {
    /* Headless? Free our images and clear the slot. */
    pthread_mutex_lock(&g_headless_mutex);
    GpaHeadlessSwapchain *hsc = find_headless_swapchain(swapchain);
    if (hsc) {
        GpaDeviceDispatch *ddisp = gpa_device_dispatch_get(device);
        PFN_vkDestroyImage destroy_image = NULL;
        if (ddisp && ddisp->GetDeviceProcAddr)
            destroy_image = (PFN_vkDestroyImage)
                ddisp->GetDeviceProcAddr(device, "vkDestroyImage");
        for (uint32_t i = 0; i < hsc->image_count; i++) {
            if (destroy_image && hsc->images[i] != VK_NULL_HANDLE)
                destroy_image(device, hsc->images[i], NULL);
            if (ddisp && ddisp->FreeMemory && hsc->memories[i] != VK_NULL_HANDLE)
                ddisp->FreeMemory(device, hsc->memories[i], NULL);
        }
        memset(hsc, 0, sizeof(*hsc));
        pthread_mutex_unlock(&g_headless_mutex);
        /* Also remove the legacy SwapchainInfo entry */
        for (uint32_t i = 0; i < g_swapchain_count; i++) {
            if (g_swapchains[i].swapchain == swapchain) {
                g_swapchains[i] = g_swapchains[--g_swapchain_count];
                break;
            }
        }
        (void)pAllocator;
        return;
    }
    pthread_mutex_unlock(&g_headless_mutex);

    /* Remove from legacy tracking table */
    for (uint32_t i = 0; i < g_swapchain_count; i++) {
        if (g_swapchains[i].swapchain == swapchain) {
            g_swapchains[i] = g_swapchains[--g_swapchain_count];
            break;
        }
    }

    GpaDeviceDispatch *disp = gpa_device_dispatch_get(device);
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
gpa_vkGetDeviceProcAddr(VkDevice device, const char *pName) {
#define INTERCEPT(fn) \
    if (strcmp(pName, "vk" #fn) == 0) return (PFN_vkVoidFunction)gpa_##fn

    if (strcmp(pName, "vkGetDeviceProcAddr") == 0)
        return (PFN_vkVoidFunction)gpa_vkGetDeviceProcAddr;
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
    INTERCEPT(AcquireNextImageKHR);
#undef INTERCEPT

    if (device == VK_NULL_HANDLE) return NULL;
    GpaDeviceDispatch *disp = gpa_device_dispatch_get(device);
    if (disp && disp->GetDeviceProcAddr)
        return disp->GetDeviceProcAddr(device, pName);
    return NULL;
}

/* --------------------------------------------------------------------------
 * vkGetInstanceProcAddr — return our intercepts or chain down
 * -------------------------------------------------------------------------- */

/* --------------------------------------------------------------------------
 * VK_EXT_headless_surface support (loader-validation unblock for chromium)
 *
 * Chromium's --use-angle=vulkan path requests VK_EXT_headless_surface as
 * an instance extension when --headless=new is set. If no ICD reports
 * support, the loader's loader_validate_instance_extensions() rejects the
 * vkCreateInstance call with VK_ERROR_EXTENSION_NOT_PRESENT.
 *
 * Our layer advertises VK_EXT_headless_surface via vkEnumerateInstance-
 * ExtensionProperties("VK_LAYER_GPA_capture", ...) so the loader sees it
 * as supplied by an enabled layer and validation passes. The actual
 * vkCreateHeadlessSurfaceEXT entrypoint chains down — modern Vulkan
 * loaders provide a built-in implementation for any headless surface.
 * -------------------------------------------------------------------------- */

static VKAPI_ATTR VkResult VKAPI_CALL
gpa_vkEnumerateInstanceExtensionProperties(const char *pLayerName,
                                            uint32_t *pPropertyCount,
                                            VkExtensionProperties *pProperties) {
    if (pLayerName == NULL || strcmp(pLayerName, "VK_LAYER_GPA_capture") != 0) {
        /* Not our layer query. With our layer-interface-v2, the loader
         * resolves these globally and calls the next layer / ICD. Returning
         * VK_SUCCESS with 0 properties is safe — the loader merges with
         * other sources. */
        if (pPropertyCount) *pPropertyCount = 0;
        return VK_SUCCESS;
    }

    /* Extensions provided by our layer */
    static const VkExtensionProperties gpa_layer_exts[] = {
        { "VK_EXT_headless_surface", 1 },
    };
    const uint32_t n = (uint32_t)(sizeof(gpa_layer_exts) / sizeof(gpa_layer_exts[0]));

    if (pProperties == NULL) {
        *pPropertyCount = n;
        return VK_SUCCESS;
    }
    uint32_t copy = (*pPropertyCount < n) ? *pPropertyCount : n;
    if (copy > 0) memcpy(pProperties, gpa_layer_exts, copy * sizeof(VkExtensionProperties));
    *pPropertyCount = copy;
    return (copy < n) ? VK_INCOMPLETE : VK_SUCCESS;
}

static VKAPI_ATTR VkResult VKAPI_CALL
gpa_vkCreateHeadlessSurfaceEXT(VkInstance instance,
                                const VkHeadlessSurfaceCreateInfoEXT *pCreateInfo,
                                const VkAllocationCallbacks *pAllocator,
                                VkSurfaceKHR *pSurface) {
    (void)pCreateInfo; (void)pAllocator;
    /* In-layer emulation — we do NOT chain down here, because no Linux ICDs
     * we target ship VK_EXT_headless_surface, and the loader trampoline
     * would route the lookup through our own GIPA again (recursion). */
    pthread_mutex_lock(&g_headless_mutex);
    GpaHeadlessSurface *slot = NULL;
    for (int i = 0; i < GPA_MAX_HEADLESS_SURFACES; i++) {
        if (!g_h_surfaces[i].in_use) { slot = &g_h_surfaces[i]; break; }
    }
    if (!slot) {
        pthread_mutex_unlock(&g_headless_mutex);
        return VK_ERROR_OUT_OF_HOST_MEMORY;
    }
    slot->magic    = GPA_HEADLESS_MAGIC;
    slot->in_use   = 1;
    slot->instance = instance;
    *pSurface = (VkSurfaceKHR)(uintptr_t)slot;
    pthread_mutex_unlock(&g_headless_mutex);
    fprintf(stderr, "[OpenGPA-VK] emulated headless surface %p\n", (void*)slot);
    return VK_SUCCESS;
}

static VKAPI_ATTR void VKAPI_CALL
gpa_vkDestroySurfaceKHR(VkInstance instance,
                         VkSurfaceKHR surface,
                         const VkAllocationCallbacks *pAllocator) {
    pthread_mutex_lock(&g_headless_mutex);
    GpaHeadlessSurface *hsfc = find_headless_surface(surface);
    if (hsfc) {
        memset(hsfc, 0, sizeof(*hsfc));
        pthread_mutex_unlock(&g_headless_mutex);
        return;
    }
    pthread_mutex_unlock(&g_headless_mutex);
    GpaInstanceDispatch *disp = gpa_instance_dispatch_get(instance);
    if (disp && disp->DestroySurfaceKHR)
        disp->DestroySurfaceKHR(instance, surface, pAllocator);
}

static VKAPI_ATTR VkResult VKAPI_CALL
gpa_vkGetPhysicalDeviceSurfaceSupportKHR(VkPhysicalDevice physDev,
                                          uint32_t queueFamilyIndex,
                                          VkSurfaceKHR surface,
                                          VkBool32 *pSupported) {
    (void)queueFamilyIndex;
    pthread_mutex_lock(&g_headless_mutex);
    int is_ours = find_headless_surface(surface) != NULL;
    pthread_mutex_unlock(&g_headless_mutex);
    if (is_ours) { *pSupported = VK_TRUE; return VK_SUCCESS; }
    GpaInstanceDispatch *disp = gpa_instance_dispatch_get((VkInstance)physDev);
    if (disp && disp->GetPhysicalDeviceSurfaceSupportKHR)
        return disp->GetPhysicalDeviceSurfaceSupportKHR(physDev, queueFamilyIndex,
                                                          surface, pSupported);
    return VK_ERROR_SURFACE_LOST_KHR;
}

static VKAPI_ATTR VkResult VKAPI_CALL
gpa_vkGetPhysicalDeviceSurfaceCapabilitiesKHR(VkPhysicalDevice physDev,
                                               VkSurfaceKHR surface,
                                               VkSurfaceCapabilitiesKHR *pCaps) {
    pthread_mutex_lock(&g_headless_mutex);
    int is_ours = find_headless_surface(surface) != NULL;
    pthread_mutex_unlock(&g_headless_mutex);
    if (is_ours) {
        memset(pCaps, 0, sizeof(*pCaps));
        pCaps->minImageCount = 2;
        pCaps->maxImageCount = GPA_MAX_HEADLESS_IMAGES;
        /* 0xFFFFFFFF means "match what the swapchain requests" */
        pCaps->currentExtent.width  = 0xFFFFFFFFu;
        pCaps->currentExtent.height = 0xFFFFFFFFu;
        pCaps->minImageExtent.width  = 1;
        pCaps->minImageExtent.height = 1;
        pCaps->maxImageExtent.width  = 16384;
        pCaps->maxImageExtent.height = 16384;
        pCaps->maxImageArrayLayers = 1;
        pCaps->supportedTransforms = VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR;
        pCaps->currentTransform    = VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR;
        pCaps->supportedCompositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
        pCaps->supportedUsageFlags = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT |
                                       VK_IMAGE_USAGE_TRANSFER_SRC_BIT |
                                       VK_IMAGE_USAGE_TRANSFER_DST_BIT |
                                       VK_IMAGE_USAGE_SAMPLED_BIT |
                                       VK_IMAGE_USAGE_STORAGE_BIT;
        return VK_SUCCESS;
    }
    GpaInstanceDispatch *disp = gpa_instance_dispatch_get((VkInstance)physDev);
    if (disp && disp->GetPhysicalDeviceSurfaceCapabilitiesKHR)
        return disp->GetPhysicalDeviceSurfaceCapabilitiesKHR(physDev, surface, pCaps);
    return VK_ERROR_SURFACE_LOST_KHR;
}

static VKAPI_ATTR VkResult VKAPI_CALL
gpa_vkGetPhysicalDeviceSurfaceFormatsKHR(VkPhysicalDevice physDev,
                                          VkSurfaceKHR surface,
                                          uint32_t *pSurfaceFormatCount,
                                          VkSurfaceFormatKHR *pSurfaceFormats) {
    pthread_mutex_lock(&g_headless_mutex);
    int is_ours = find_headless_surface(surface) != NULL;
    pthread_mutex_unlock(&g_headless_mutex);
    if (is_ours) {
        static const VkSurfaceFormatKHR formats[] = {
            { VK_FORMAT_B8G8R8A8_UNORM, VK_COLOR_SPACE_SRGB_NONLINEAR_KHR },
            { VK_FORMAT_R8G8B8A8_UNORM, VK_COLOR_SPACE_SRGB_NONLINEAR_KHR },
        };
        const uint32_t n = (uint32_t)(sizeof(formats) / sizeof(formats[0]));
        if (!pSurfaceFormats) { *pSurfaceFormatCount = n; return VK_SUCCESS; }
        uint32_t copy = (*pSurfaceFormatCount < n) ? *pSurfaceFormatCount : n;
        if (copy) memcpy(pSurfaceFormats, formats, copy * sizeof(formats[0]));
        *pSurfaceFormatCount = copy;
        return (copy < n) ? VK_INCOMPLETE : VK_SUCCESS;
    }
    GpaInstanceDispatch *disp = gpa_instance_dispatch_get((VkInstance)physDev);
    if (disp && disp->GetPhysicalDeviceSurfaceFormatsKHR)
        return disp->GetPhysicalDeviceSurfaceFormatsKHR(physDev, surface,
                                                          pSurfaceFormatCount,
                                                          pSurfaceFormats);
    return VK_ERROR_SURFACE_LOST_KHR;
}

static VKAPI_ATTR VkResult VKAPI_CALL
gpa_vkGetPhysicalDeviceSurfacePresentModesKHR(VkPhysicalDevice physDev,
                                                VkSurfaceKHR surface,
                                                uint32_t *pPresentModeCount,
                                                VkPresentModeKHR *pPresentModes) {
    pthread_mutex_lock(&g_headless_mutex);
    int is_ours = find_headless_surface(surface) != NULL;
    pthread_mutex_unlock(&g_headless_mutex);
    if (is_ours) {
        static const VkPresentModeKHR modes[] = { VK_PRESENT_MODE_FIFO_KHR };
        const uint32_t n = 1;
        if (!pPresentModes) { *pPresentModeCount = n; return VK_SUCCESS; }
        uint32_t copy = (*pPresentModeCount < n) ? *pPresentModeCount : n;
        if (copy) memcpy(pPresentModes, modes, copy * sizeof(modes[0]));
        *pPresentModeCount = copy;
        return (copy < n) ? VK_INCOMPLETE : VK_SUCCESS;
    }
    GpaInstanceDispatch *disp = gpa_instance_dispatch_get((VkInstance)physDev);
    if (disp && disp->GetPhysicalDeviceSurfacePresentModesKHR)
        return disp->GetPhysicalDeviceSurfacePresentModesKHR(physDev, surface,
                                                               pPresentModeCount,
                                                               pPresentModes);
    return VK_ERROR_SURFACE_LOST_KHR;
}

VK_LAYER_EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
gpa_vkGetInstanceProcAddr(VkInstance instance, const char *pName) {
    /* Layer negotiation */
    if (strcmp(pName, "vkNegotiateLoaderLayerInterfaceVersion") == 0)
        return (PFN_vkVoidFunction)vkNegotiateLoaderLayerInterfaceVersion;

    /* Pre-instance / global functions (instance == VK_NULL_HANDLE) */
    if (strcmp(pName, "vkEnumerateInstanceExtensionProperties") == 0)
        return (PFN_vkVoidFunction)gpa_vkEnumerateInstanceExtensionProperties;

    /* Extension entrypoints we provide */
    if (strcmp(pName, "vkCreateHeadlessSurfaceEXT") == 0)
        return (PFN_vkVoidFunction)gpa_vkCreateHeadlessSurfaceEXT;
    if (strcmp(pName, "vkDestroySurfaceKHR") == 0)
        return (PFN_vkVoidFunction)gpa_vkDestroySurfaceKHR;
    if (strcmp(pName, "vkGetPhysicalDeviceSurfaceSupportKHR") == 0)
        return (PFN_vkVoidFunction)gpa_vkGetPhysicalDeviceSurfaceSupportKHR;
    if (strcmp(pName, "vkGetPhysicalDeviceSurfaceCapabilitiesKHR") == 0)
        return (PFN_vkVoidFunction)gpa_vkGetPhysicalDeviceSurfaceCapabilitiesKHR;
    if (strcmp(pName, "vkGetPhysicalDeviceSurfaceFormatsKHR") == 0)
        return (PFN_vkVoidFunction)gpa_vkGetPhysicalDeviceSurfaceFormatsKHR;
    if (strcmp(pName, "vkGetPhysicalDeviceSurfacePresentModesKHR") == 0)
        return (PFN_vkVoidFunction)gpa_vkGetPhysicalDeviceSurfacePresentModesKHR;

    /* Instance-level intercepts */
#define INTERCEPT(fn) \
    if (strcmp(pName, "vk" #fn) == 0) return (PFN_vkVoidFunction)gpa_##fn

    if (strcmp(pName, "vkGetInstanceProcAddr") == 0)
        return (PFN_vkVoidFunction)gpa_vkGetInstanceProcAddr;
    INTERCEPT(CreateInstance);
    INTERCEPT(DestroyInstance);
    INTERCEPT(CreateDevice);
    INTERCEPT(EnumeratePhysicalDevices);
#undef INTERCEPT

    /* Device-level functions also queryable via GetInstanceProcAddr */
    PFN_vkVoidFunction dev_fn = gpa_vkGetDeviceProcAddr(VK_NULL_HANDLE, pName);
    if (dev_fn) return dev_fn;

    /* Chain to the next layer */
    if (instance == VK_NULL_HANDLE) return NULL;
    GpaInstanceDispatch *disp = gpa_instance_dispatch_get(instance);
    if (disp && disp->GetInstanceProcAddr)
        return disp->GetInstanceProcAddr(instance, pName);
    return NULL;
}

/* --------------------------------------------------------------------------
 * vkNegotiateLoaderLayerInterfaceVersion — required by the loader
 * -------------------------------------------------------------------------- */

/* Plain-name aliases for layer-interface-version-0 / legacy loaders that
 * look up vkGetInstanceProcAddr / vkGetDeviceProcAddr by exact symbol name
 * instead of going through vkNegotiateLoaderLayerInterfaceVersion. Loaders
 * dlopen the layer .so with handle-scoped dlsym, so plain names here do
 * not interpose globally. */
VK_LAYER_EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
vkGetInstanceProcAddr(VkInstance instance, const char *pName) {
    return gpa_vkGetInstanceProcAddr(instance, pName);
}

VK_LAYER_EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
vkGetDeviceProcAddr(VkDevice device, const char *pName) {
    return gpa_vkGetDeviceProcAddr(device, pName);
}

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
        pVersionStruct->pfnGetInstanceProcAddr = gpa_vkGetInstanceProcAddr;
        pVersionStruct->pfnGetDeviceProcAddr   = gpa_vkGetDeviceProcAddr;
        pVersionStruct->pfnGetPhysicalDeviceProcAddr = NULL;
    }

    return VK_SUCCESS;
}
