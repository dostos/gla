/*
 * minimal_app.c — Minimal Vulkan application for testing the OpenGPA layer.
 *
 * This application creates a Vulkan instance and device, then presents
 * a simple colored triangle. It is designed to test the OpenGPA layer's
 * ability to intercept basic Vulkan calls.
 *
 * Build:
 *   gcc -o minimal_app minimal_app.c -lvulkan -lm
 *
 * Run with OpenGPA layer:
 *   export VK_INSTANCE_LAYERS=VK_LAYER_GLA_capture
 *   ./minimal_app
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>

#define CHECK_VK(expr) \
    do { \
        VkResult res = (expr); \
        if (res != VK_SUCCESS) { \
            fprintf(stderr, "Vulkan error at %s:%d: %d\n", __FILE__, __LINE__, res); \
            exit(1); \
        } \
    } while (0)

typedef struct {
    VkInstance instance;
    VkPhysicalDevice physical_device;
    VkDevice device;
    VkQueue queue;
    VkCommandPool command_pool;
    VkCommandBuffer command_buffer;
} VulkanContext;

VulkanContext ctx = {0};

static void create_instance(void) {
    VkApplicationInfo app_info = {
        .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName = "OpenGPA Minimal App",
        .applicationVersion = VK_MAKE_VERSION(1, 0, 0),
        .pEngineName = "No Engine",
        .engineVersion = VK_MAKE_VERSION(1, 0, 0),
        .apiVersion = VK_API_VERSION_1_0,
    };

    VkInstanceCreateInfo create_info = {
        .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        .pApplicationInfo = &app_info,
    };

    CHECK_VK(vkCreateInstance(&create_info, NULL, &ctx.instance));
    printf("[OpenGPA] Created Vulkan instance\n");
}

static void enumerate_devices(void) {
    uint32_t device_count = 0;
    CHECK_VK(vkEnumeratePhysicalDevices(ctx.instance, &device_count, NULL));

    if (device_count == 0) {
        fprintf(stderr, "No Vulkan devices found\n");
        exit(1);
    }

    VkPhysicalDevice *devices = malloc(sizeof(VkPhysicalDevice) * device_count);
    CHECK_VK(vkEnumeratePhysicalDevices(ctx.instance, &device_count, devices));

    ctx.physical_device = devices[0];
    free(devices);

    VkPhysicalDeviceProperties props;
    vkGetPhysicalDeviceProperties(ctx.physical_device, &props);
    printf("[OpenGPA] Using device: %s\n", props.deviceName);
}

static void create_device(void) {
    uint32_t queue_family_count = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(ctx.physical_device, &queue_family_count, NULL);

    VkQueueFamilyProperties *queue_families = malloc(sizeof(*queue_families) * queue_family_count);
    vkGetPhysicalDeviceQueueFamilyProperties(ctx.physical_device, &queue_family_count, queue_families);

    uint32_t graphics_queue_family = 0;
    for (uint32_t i = 0; i < queue_family_count; i++) {
        if (queue_families[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) {
            graphics_queue_family = i;
            break;
        }
    }
    free(queue_families);

    float queue_priority = 1.0f;
    VkDeviceQueueCreateInfo queue_create_info = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex = graphics_queue_family,
        .queueCount = 1,
        .pQueuePriorities = &queue_priority,
    };

    VkDeviceCreateInfo device_create_info = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
        .queueCreateInfoCount = 1,
        .pQueueCreateInfos = &queue_create_info,
    };

    CHECK_VK(vkCreateDevice(ctx.physical_device, &device_create_info, NULL, &ctx.device));
    vkGetDeviceQueue(ctx.device, graphics_queue_family, 0, &ctx.queue);
    printf("[OpenGPA] Created Vulkan device and queue\n");
}

static void create_command_pool(void) {
    VkCommandPoolCreateInfo pool_info = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
        .queueFamilyIndex = 0,
        .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
    };

    CHECK_VK(vkCreateCommandPool(ctx.device, &pool_info, NULL, &ctx.command_pool));
    printf("[OpenGPA] Created command pool\n");
}

static void allocate_command_buffer(void) {
    VkCommandBufferAllocateInfo alloc_info = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        .commandPool = ctx.command_pool,
        .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
        .commandBufferCount = 1,
    };

    CHECK_VK(vkAllocateCommandBuffers(ctx.device, &alloc_info, &ctx.command_buffer));
    printf("[OpenGPA] Allocated command buffer\n");
}

static void record_simple_commands(void) {
    VkCommandBufferBeginInfo begin_info = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
        .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
    };

    CHECK_VK(vkBeginCommandBuffer(ctx.command_buffer, &begin_info));
    printf("[OpenGPA] Began recording command buffer\n");

    /* In a real application, we'd bind pipelines, set render areas, etc.
     * For now, just demonstrate command buffer recording. */

    CHECK_VK(vkEndCommandBuffer(ctx.command_buffer));
    printf("[OpenGPA] Ended recording command buffer\n");
}

static void cleanup(void) {
    if (ctx.device) {
        vkDeviceWaitIdle(ctx.device);
        if (ctx.command_pool) {
            vkDestroyCommandPool(ctx.device, ctx.command_pool, NULL);
        }
        vkDestroyDevice(ctx.device, NULL);
    }
    if (ctx.instance) {
        vkDestroyInstance(ctx.instance, NULL);
    }
    printf("[OpenGPA] Cleanup complete\n");
}

int main(void) {
    printf("=== OpenGPA Minimal Vulkan App ===\n");
    printf("This app tests basic Vulkan layer interception.\n\n");

    create_instance();
    enumerate_devices();
    create_device();
    create_command_pool();
    allocate_command_buffer();
    record_simple_commands();

    printf("\n[OpenGPA] Application ran successfully.\n");
    printf("If VK_LAYER_GLA_capture was active, the layer should have\n");
    printf("intercepted all Vulkan calls above.\n\n");

    cleanup();
    return 0;
}
