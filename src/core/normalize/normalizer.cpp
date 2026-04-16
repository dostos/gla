#include "src/core/normalize/normalizer.h"

namespace gla {

NormalizedFrame Normalizer::normalize(const gla::store::RawFrame& raw) const {
    NormalizedFrame frame;
    frame.frame_id = raw.frame_id;
    frame.timestamp = raw.timestamp;

    // V1: all draw calls go into a single implicit render pass
    RenderPass pass;
    pass.target_framebuffer = 0;

    for (const auto& rdc : raw.draw_calls) {
        NormalizedDrawCall dc;
        dc.id             = rdc.id;
        dc.primitive_type = rdc.primitive_type;
        dc.vertex_count   = rdc.vertex_count;
        dc.index_count    = rdc.index_count;
        dc.instance_count = rdc.instance_count;
        dc.shader_id      = rdc.shader_program_id;

        // Shader parameters
        dc.params.reserve(rdc.params.size());
        for (const auto& p : rdc.params) {
            ShaderParameter sp;
            sp.name = p.name;
            sp.type = p.type;
            sp.data = p.data;
            dc.params.push_back(std::move(sp));
        }

        // Texture bindings
        dc.textures.reserve(rdc.textures.size());
        for (const auto& t : rdc.textures) {
            TextureBinding tb;
            tb.slot       = t.slot;
            tb.texture_id = t.texture_id;
            tb.width      = t.width;
            tb.height     = t.height;
            tb.format     = t.format;
            dc.textures.push_back(std::move(tb));
        }

        // Pipeline state (1:1 mapping from GL)
        const auto& rp = rdc.pipeline;
        NormalizedPipelineState& np = dc.pipeline;
        np.viewport[0]     = rp.viewport[0];
        np.viewport[1]     = rp.viewport[1];
        np.viewport[2]     = rp.viewport[2];
        np.viewport[3]     = rp.viewport[3];
        np.scissor[0]      = rp.scissor[0];
        np.scissor[1]      = rp.scissor[1];
        np.scissor[2]      = rp.scissor[2];
        np.scissor[3]      = rp.scissor[3];
        np.scissor_enabled = rp.scissor_enabled;
        np.depth_test      = rp.depth_test;
        np.depth_write     = rp.depth_write;
        np.depth_func      = rp.depth_func;
        np.blend_enabled   = rp.blend_enabled;
        np.blend_src       = rp.blend_src;
        np.blend_dst       = rp.blend_dst;
        np.cull_enabled    = rp.cull_enabled;
        np.cull_mode       = rp.cull_mode;
        np.front_face      = rp.front_face;

        // Vertex attributes
        dc.attributes.reserve(rdc.attributes.size());
        for (const auto& a : rdc.attributes) {
            VertexAttribute va;
            va.location   = a.location;
            va.format     = a.format;
            va.components = a.components;
            va.stride     = a.stride;
            va.offset     = a.offset;
            dc.attributes.push_back(std::move(va));
        }

        // Bulk data copies
        dc.vertex_data = rdc.vertex_data;
        dc.index_data  = rdc.index_data;

        pass.draw_calls.push_back(std::move(dc));
    }

    frame.render_passes.push_back(std::move(pass));

    // Framebuffer
    frame.fb_width   = raw.fb_width;
    frame.fb_height  = raw.fb_height;
    frame.fb_color   = raw.fb_color;
    frame.fb_depth   = raw.fb_depth;
    frame.fb_stencil = raw.fb_stencil;

    return frame;
}

}  // namespace gla
