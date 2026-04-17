#ifndef GLA_LAYER_H
#define GLA_LAYER_H

/*
 * gla_layer.h — Vulkan layer entry points for VK_LAYER_GLA_capture.
 *
 * The layer intercepts Vulkan API calls via dispatch table chaining.
 * The Vulkan loader requires the layer to export:
 *   - vkGetInstanceProcAddr
 *   - vkGetDeviceProcAddr
 *   - vkNegotiateLoaderLayerInterfaceVersion
 *
 * All exported symbols use VK_LAYER_EXPORT (visibility("default")).
 */

#include <vulkan/vk_layer.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Required loader negotiation entry point */
VK_LAYER_EXPORT VKAPI_ATTR VkResult VKAPI_CALL
vkNegotiateLoaderLayerInterfaceVersion(VkNegotiateLayerInterface *pVersionStruct);

/* Instance-level dispatch entry */
VK_LAYER_EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
gla_vkGetInstanceProcAddr(VkInstance instance, const char *pName);

/* Device-level dispatch entry */
VK_LAYER_EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
gla_vkGetDeviceProcAddr(VkDevice device, const char *pName);

#ifdef __cplusplus
}
#endif

#endif /* GLA_LAYER_H */
