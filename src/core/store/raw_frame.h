#pragma once
#include <array>
#include <cstdint>
#include <vector>
#include <string>

namespace gpa::store {

// Represents raw data for a single draw call as captured by the shim
struct RawDrawCall {
    uint32_t id;
    uint32_t primitive_type;  // GL enum
    uint32_t vertex_count;
    uint32_t index_count;
    uint32_t instance_count;
    uint32_t shader_program_id;

    // Shader parameters (serialized from FlatBuffer)
    struct Param {
        std::string name;
        uint32_t type;
        std::vector<uint8_t> data;
    };
    std::vector<Param> params;

    // Texture bindings
    struct Texture {
        uint32_t slot;
        uint32_t texture_id;
        uint32_t width, height, format;
    };
    std::vector<Texture> textures;

    // Pipeline state
    struct Pipeline {
        int32_t viewport[4];
        int32_t scissor[4];
        bool scissor_enabled;
        bool depth_test, depth_write;
        uint32_t depth_func;
        bool blend_enabled;
        uint32_t blend_src, blend_dst;
        bool cull_enabled;
        uint32_t cull_mode, front_face;
    } pipeline;

    // Bulk data (vertex buffer, index buffer contents)
    std::vector<uint8_t> vertex_data;
    std::vector<uint8_t> index_data;

    // Vertex attributes
    struct VertexAttr {
        uint32_t location, format, components, stride, offset;
    };
    std::vector<VertexAttr> attributes;

    std::string debug_group_path;

    // FBO attachment info (color attachment texture ID at time of draw).
    // `fbo_color_attachment_tex` is kept equal to fbo_color_attachments[0]
    // for backward compatibility with existing consumers.
    uint32_t fbo_color_attachment_tex = 0;

    // Full MRT color-attachment table (GL_COLOR_ATTACHMENT0..7).
    // Entries are 0 when the slot is unbound.
    std::array<uint32_t, 8> fbo_color_attachments{};

    // GL index type enum for indexed draws (GL_UNSIGNED_SHORT/INT/BYTE); 0 for glDrawArrays*
    uint32_t index_type = 0;
};

// A per-frame glClear record
struct RawClearRecord {
    uint32_t mask;             // GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT
    uint32_t draw_call_before; // how many draw calls had already been issued before this clear
};

// A captured frame
struct RawFrame {
    uint64_t frame_id;
    double timestamp;
    uint32_t api_type;  // 0=GL, 1=VK, 2=WebGL

    std::vector<RawDrawCall> draw_calls;

    // glClear calls recorded this frame
    std::vector<RawClearRecord> clear_records;

    // Framebuffer data
    uint32_t fb_width, fb_height;
    std::vector<uint8_t> fb_color;    // RGBA, size = w*h*4
    std::vector<float> fb_depth;      // size = w*h
    std::vector<uint8_t> fb_stencil;  // size = w*h
};

}  // namespace gpa::store
