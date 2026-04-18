# OpenGPA Vulkan Test App

This guide explains how to build and run the minimal Vulkan test application that validates the OpenGPA layer's interception capabilities.

## Overview

The test app (`examples/vulkan/minimal_app.c`) demonstrates:
- Creating a Vulkan instance
- Enumerating and selecting a physical device
- Creating a logical device and queue
- Creating a command pool
- Recording simple command buffers

It serves as a minimal, reproducible example for testing OpenGPA layer installation and functionality.

## Requirements

- **Vulkan SDK**: Headers and libraries
  - Linux: `libvulkan-dev` and `libvulkan1` packages
  - Or install the [Vulkan SDK](https://vulkan.lunarg.com/sdk/home)
- **C Compiler**: GCC or Clang with C11 support
- **OpenGPA Layer**: Built and installed (see [vulkan-layer.md](./vulkan-layer.md))

## Verify Vulkan SDK

Before building, check that Vulkan headers and libraries are available:

```bash
# Check for headers
ls -la /usr/include/vulkan/vulkan.h

# Check for libraries
ldconfig -p | grep libvulkan
```

If not found, install the Vulkan SDK:

```bash
# Debian/Ubuntu
sudo apt-get install libvulkan-dev libvulkan1

# Or from vulkan.lunarg.com
```

## Building the Test App

From the repository root:

```bash
cd examples/vulkan
make
```

This produces the `minimal_app` executable.

### Manual Compilation

If Makefile doesn't work:

```bash
gcc -o minimal_app minimal_app.c -lvulkan -lm
```

## Running Without the OpenGPA Layer

To verify the app runs without the layer:

```bash
cd examples/vulkan
./minimal_app
```

Expected output:
```
=== OpenGPA Minimal Vulkan App ===
This app tests basic Vulkan layer interception.

[OpenGPA] Created Vulkan instance
[OpenGPA] Using device: <your GPU name>
[OpenGPA] Created Vulkan device and queue
[OpenGPA] Created command pool
[OpenGPA] Allocated command buffer
[OpenGPA] Ended recording command buffer

[OpenGPA] Application ran successfully.
If VK_LAYER_GLA_capture was active, the layer should have
intercepted all Vulkan calls above.

[OpenGPA] Cleanup complete
```

## Running With the OpenGPA Layer

First, ensure the OpenGPA layer is installed (see [vulkan-layer.md](./vulkan-layer.md) installation section).

### Using Make Target

```bash
cd examples/vulkan
make run
```

This sets `VK_INSTANCE_LAYERS=VK_LAYER_GLA_capture` and runs the app.

### Manual Execution

```bash
export VK_INSTANCE_LAYERS=VK_LAYER_GLA_capture
./minimal_app
```

### Debugging Layer Loading

If the layer doesn't appear to load:

```bash
cd examples/vulkan
make debug
```

Or manually:

```bash
export VK_INSTANCE_LAYERS=VK_LAYER_GLA_capture
export VK_LAYER_PATH=~/.config/vulkan/implicit_layer.d
export VK_LOADER_DEBUG=all
./minimal_app 2>&1 | grep -i gla
```

This enables Vulkan loader debug output and filters for OpenGPA-related messages.

## Interpreting Results

### Success Indicators
- App runs without errors
- All `[OpenGPA]` tagged output lines appear
- No "layer not found" or "symbol not found" errors

### Common Issues

**Layer not found**: Check that the `.json` manifest and `.so` file are in the correct directory:
```bash
ls -la ~/.config/vulkan/implicit_layer.d/
```

**Symbol not found**: Ensure the `.so` was built correctly:
```bash
ldd ~/.config/vulkan/implicit_layer.d/libVkLayer_gla_capture.so
```

**Device not found**: Your system must have a Vulkan-capable GPU. Check:
```bash
vulkaninfo | grep deviceName
```

## Expected OpenGPA Layer Behavior

When the layer is active, it should intercept and log:
- `vkCreateInstance`
- `vkEnumeratePhysicalDevices`
- `vkGetPhysicalDeviceProperties`
- `vkCreateDevice`
- `vkGetDeviceQueue`
- `vkCreateCommandPool`
- `vkAllocateCommandBuffers`
- `vkBeginCommandBuffer`
- `vkEndCommandBuffer`
- `vkDestroyCommandPool`
- `vkDestroyDevice`
- `vkDestroyInstance`

The layer should relay frame metadata and capture state to the OpenGPA engine via IPC (Unix socket by default).

## Extending the Test App

To add more functionality:

1. **Render passes**: Add `vkCreateRenderPass`, `vkBeginRenderPass`, `vkEndRenderPass`
2. **Pipelines**: Add graphics pipeline creation and binding
3. **Buffers**: Add vertex/index buffer creation and updates
4. **Descriptors**: Add descriptor set layout and binding
5. **Synchronization**: Add semaphores and fences for frame coordination

See the [Vulkan specification](https://registry.khronos.org/vulkan/) and [Khronos tutorials](https://vulkan-tutorial.com/) for deeper examples.

## Integration with OpenGPA Engine

To validate full integration:

1. Start the OpenGPA engine listening on `/tmp/gla.sock`
2. Ensure OpenGPA core services are running
3. Run the test app with the layer enabled
4. Check engine logs for captured frame data

Refer to the [OpenGPA engine documentation](../README.md) for engine setup.
