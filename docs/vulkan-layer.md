# OpenGPA Vulkan Layer — Setup and Usage

The OpenGPA Vulkan layer (`VK_LAYER_GLA_capture`) intercepts Vulkan API calls to capture graphics frame data, driver state, and resource operations for debugging and analysis.

## Architecture

```
Vulkan Application
       |
       v
VK_LAYER_GLA_capture (dispatch table chaining)
       |
       | IPC (Unix socket or shared memory)
       v
OpenGPA Engine
```

The layer uses the standard Vulkan loader layer mechanism. It exports the required dispatch table functions:
- `vkGetInstanceProcAddr` — routes instance-level calls
- `vkGetDeviceProcAddr` — routes device-level calls
- `vkNegotiateLoaderLayerInterfaceVersion` — loader negotiation

## Building the Layer

The layer is built with Bazel:

```bash
bazel build //src/shims/vk:VkLayer_gla_capture
```

This produces:
```
bazel-bin/src/shims/vk/libVkLayer_gla_capture.so
```

## Installation

The Vulkan loader discovers layers via JSON manifest files in implicit layer directories.

### Step 1: Locate the Implicit Layer Directory

Typically:
- **Linux**: `/etc/vulkan/implicit_layer.d/` (system-wide) or `~/.config/vulkan/implicit_layer.d/` (user)
- **macOS**: `~/.config/vulkan/implicit_layer.d/`
- **Windows**: `%APPDATA%\vulkan\implicit_layer.d\` or system registry

### Step 2: Copy the Layer Files

```bash
# Build the layer
bazel build //src/shims/vk:VkLayer_gla_capture

# Copy .so and manifest (example for user layer directory)
mkdir -p ~/.config/vulkan/implicit_layer.d
cp bazel-bin/src/shims/vk/libVkLayer_gla_capture.so ~/.config/vulkan/implicit_layer.d/
cp src/shims/vk/gla_layer.json ~/.config/vulkan/implicit_layer.d/
```

### Step 3: Update Manifest Path (if needed)

The manifest (`gla_layer.json`) references `library_path: "./libVkLayer_gla_capture.so"` as a relative path. Ensure it can be resolved:

```json
{
    "file_format_version": "1.0.0",
    "layer": {
        "name": "VK_LAYER_GLA_capture",
        "type": "GLOBAL",
        "library_path": "/full/path/to/libVkLayer_gla_capture.so",
        "api_version": "1.0.0",
        "implementation_version": "1",
        "description": "OpenGPA frame capture layer for graphics debugging"
    }
}
```

Or ensure both `.so` and `.json` are in the same directory.

## Activation

Set the `VK_INSTANCE_LAYERS` environment variable before running a Vulkan application:

```bash
export VK_INSTANCE_LAYERS=VK_LAYER_GLA_capture
./my_vulkan_app
```

### Debugging Layer Loading

If the layer fails to load, check debug output:

```bash
export VK_INSTANCE_LAYERS=VK_LAYER_GLA_capture
export VK_LAYER_PATH=~/.config/vulkan/implicit_layer.d
# On Linux, may produce loader debug output
VK_LOADER_DEBUG=all ./my_vulkan_app 2>&1 | grep -i gla
```

## Current Limitations

### Capture Scope
- **Device creation & command recording**: Full interception of device, command buffer, and render pass creation.
- **Dispatch chaining**: All Vulkan API calls are routed through the layer.

### Known Gaps (v1)
- **No frame-level synchronization markers**: Frames are not automatically detected; you must signal frame boundaries via IPC commands to the engine.
- **Memory barrier tracking**: Memory barriers and synchronization primitives are intercepted but detailed analysis (hazard detection, false dependencies) is not yet implemented.
- **Dynamic render pass tracking**: VK_KHR_dynamic_rendering is intercepted but per-fragment state transitions may not be fully captured.
- **Shader reflection**: No automatic SPIR-V reflection; shader bindings are inferred from descriptor set layouts.

### Performance
- Layer adds overhead proportional to API call volume. For high call-rate applications, consider:
  - Running with the layer only when needed
  - Enabling selective capture (frame range via IPC)

## Integration with OpenGPA Engine

The layer communicates with the OpenGPA engine via:
- **IPC client**: `vk_ipc_client.c` — connects to engine over Unix socket or shared memory
- **Capture state**: `vk_capture.c` — buffers and serializes frame data
- **Dispatch table**: `vk_dispatch.c` — intercepts and routes API calls

To integrate, ensure the engine is listening on the configured IPC endpoint (default: `/tmp/gla.sock`) before the layer is loaded.

## Testing

See the [Vulkan test app guide](./vulkan-test-app.md) for how to build and run a minimal Vulkan application with the OpenGPA layer.
