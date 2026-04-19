#pragma once
#include <array>
#include <cstdint>
#include <vector>
#include <string>
#include <functional>

namespace gpa {

struct NormalizedPipelineState {
    int32_t viewport[4];    // x, y, w, h
    int32_t scissor[4];
    bool scissor_enabled = false;
    bool depth_test = false;
    bool depth_write = true;
    uint32_t depth_func = 0;
    bool blend_enabled = false;
    uint32_t blend_src = 0, blend_dst = 0;
    bool cull_enabled = false;
    uint32_t cull_mode = 0;
    uint32_t front_face = 0;
};

struct ShaderParameter {
    std::string name;
    uint32_t type;               // ParamType enum value
    std::vector<uint8_t> data;   // raw bytes
};

struct TextureBinding {
    uint32_t slot;
    uint32_t texture_id;
    uint32_t width, height, format;
};

struct VertexAttribute {
    uint32_t location, format, components, stride, offset;
};

struct NormalizedDrawCall {
    uint32_t id;
    uint32_t primitive_type;     // 0=triangles, 1=lines, 2=points, etc.
    uint32_t vertex_count;
    uint32_t index_count;
    uint32_t instance_count;
    uint32_t shader_id;

    std::vector<ShaderParameter> params;
    std::vector<TextureBinding> textures;
    NormalizedPipelineState pipeline;
    std::vector<VertexAttribute> attributes;

    // Bulk data (owned copy from raw frame)
    std::vector<uint8_t> vertex_data;
    std::vector<uint8_t> index_data;

    std::string debug_group_path;

    // FBO color attachment texture (for feedback loop detection).
    // `fbo_color_attachment_tex` mirrors fbo_color_attachments[0] for
    // backward compatibility with existing routes/tests.
    uint32_t fbo_color_attachment_tex = 0;

    // Full MRT color-attachment table (GL_COLOR_ATTACHMENT0..7).
    // Non-MRT draws have entries 1..7 = 0.
    std::array<uint32_t, 8> fbo_color_attachments{};

    // GL index type enum for indexed draws (GL_UNSIGNED_SHORT/INT/BYTE); 0 for glDrawArrays*
    uint32_t index_type = 0;
};

struct RenderPass {
    uint32_t target_framebuffer = 0;  // 0 = default
    std::vector<NormalizedDrawCall> draw_calls;
};

struct ClearRecord {
    uint32_t mask;             // GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT
    uint32_t draw_call_before; // how many draw calls had been issued before this clear
};

struct NormalizedFrame {
    uint64_t frame_id;
    double timestamp;

    // Draw calls grouped under render passes (v1: single implicit pass)
    std::vector<RenderPass> render_passes;

    // glClear calls recorded this frame
    std::vector<ClearRecord> clear_records;

    // Framebuffer
    uint32_t fb_width = 0, fb_height = 0;
    std::vector<uint8_t> fb_color;     // RGBA
    std::vector<float> fb_depth;       // float32
    std::vector<uint8_t> fb_stencil;   // uint8

    // Convenience: flat list of all draw calls across all passes
    std::vector<std::reference_wrapper<const NormalizedDrawCall>> all_draw_calls() const {
        std::vector<std::reference_wrapper<const NormalizedDrawCall>> result;
        for (auto& rp : render_passes) {
            for (auto& dc : rp.draw_calls) {
                result.push_back(std::cref(dc));
            }
        }
        return result;
    }
};

}  // namespace gpa
