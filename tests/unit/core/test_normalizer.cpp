#include <gtest/gtest.h>
#include "src/core/normalize/normalizer.h"
#include "src/core/store/raw_frame.h"

// Helpers to build a minimal RawDrawCall
static gla::store::RawDrawCall make_draw_call(uint32_t id) {
    gla::store::RawDrawCall dc{};
    dc.id             = id;
    dc.primitive_type = 4;   // GL_TRIANGLES
    dc.vertex_count   = 3;
    dc.index_count    = 0;
    dc.instance_count = 1;
    dc.shader_program_id = 42;
    // Zero-init pipeline
    dc.pipeline = {};
    return dc;
}

// ─── Test 1: Empty frame ────────────────────────────────────────────────────
TEST(NormalizerTest, EmptyFrame) {
    gla::Normalizer n;
    gla::store::RawFrame raw{};
    raw.frame_id  = 7;
    raw.timestamp = 1.23;
    raw.api_type  = 0;

    gla::NormalizedFrame f = n.normalize(raw);

    EXPECT_EQ(f.frame_id, 7u);
    EXPECT_DOUBLE_EQ(f.timestamp, 1.23);
    // V1: one implicit render pass even if empty
    ASSERT_EQ(f.render_passes.size(), 1u);
    EXPECT_TRUE(f.render_passes[0].draw_calls.empty());
    EXPECT_TRUE(f.all_draw_calls().empty());
}

// ─── Test 2: Single draw call ────────────────────────────────────────────────
TEST(NormalizerTest, SingleDrawCall) {
    gla::Normalizer n;
    gla::store::RawFrame raw{};
    raw.frame_id  = 1;
    raw.timestamp = 0.0;
    raw.api_type  = 0;
    raw.draw_calls.push_back(make_draw_call(99));

    gla::NormalizedFrame f = n.normalize(raw);

    ASSERT_EQ(f.render_passes.size(), 1u);
    ASSERT_EQ(f.render_passes[0].draw_calls.size(), 1u);

    const gla::NormalizedDrawCall& dc = f.render_passes[0].draw_calls[0];
    EXPECT_EQ(dc.id,             99u);
    EXPECT_EQ(dc.primitive_type, 4u);
    EXPECT_EQ(dc.vertex_count,   3u);
    EXPECT_EQ(dc.index_count,    0u);
    EXPECT_EQ(dc.instance_count, 1u);
    EXPECT_EQ(dc.shader_id,      42u);
}

// ─── Test 3: Multiple draw calls ─────────────────────────────────────────────
TEST(NormalizerTest, MultipleDrawCalls) {
    gla::Normalizer n;
    gla::store::RawFrame raw{};
    raw.frame_id = 2;
    for (uint32_t i = 0; i < 3; ++i) {
        raw.draw_calls.push_back(make_draw_call(i));
    }

    gla::NormalizedFrame f = n.normalize(raw);

    ASSERT_EQ(f.render_passes.size(), 1u);
    EXPECT_EQ(f.render_passes[0].draw_calls.size(), 3u);
    EXPECT_EQ(f.all_draw_calls().size(), 3u);
}

// ─── Test 4: Framebuffer copy ─────────────────────────────────────────────────
TEST(NormalizerTest, FramebufferCopy) {
    gla::Normalizer n;
    gla::store::RawFrame raw{};
    raw.frame_id  = 3;
    raw.fb_width  = 4;
    raw.fb_height = 3;
    // 4*3*4 = 48 bytes RGBA
    raw.fb_color.assign(48, 0xAB);
    // 4*3 = 12 floats depth
    raw.fb_depth.assign(12, 0.5f);
    // 4*3 = 12 bytes stencil
    raw.fb_stencil.assign(12, 0x01);

    gla::NormalizedFrame f = n.normalize(raw);

    EXPECT_EQ(f.fb_width,  4u);
    EXPECT_EQ(f.fb_height, 3u);
    ASSERT_EQ(f.fb_color.size(),   48u);
    EXPECT_EQ(f.fb_color[0],       0xABu);
    ASSERT_EQ(f.fb_depth.size(),   12u);
    EXPECT_FLOAT_EQ(f.fb_depth[0], 0.5f);
    ASSERT_EQ(f.fb_stencil.size(), 12u);
    EXPECT_EQ(f.fb_stencil[0],     0x01u);
}

// ─── Test 5: Shader params preserved ─────────────────────────────────────────
TEST(NormalizerTest, ShaderParamsPreserved) {
    gla::Normalizer n;
    gla::store::RawFrame raw{};
    raw.frame_id = 4;

    gla::store::RawDrawCall dc = make_draw_call(1);
    {
        gla::store::RawDrawCall::Param p1;
        p1.name = "uTime";
        p1.type = 1;
        p1.data = {0x00, 0x00, 0x80, 0x3F};  // 1.0f
        dc.params.push_back(p1);

        gla::store::RawDrawCall::Param p2;
        p2.name = "uColor";
        p2.type = 2;
        p2.data = {0xFF, 0x00, 0x00, 0xFF};
        dc.params.push_back(p2);
    }
    raw.draw_calls.push_back(std::move(dc));

    gla::NormalizedFrame f = n.normalize(raw);
    const auto& ndc = f.render_passes[0].draw_calls[0];

    ASSERT_EQ(ndc.params.size(), 2u);
    EXPECT_EQ(ndc.params[0].name, "uTime");
    EXPECT_EQ(ndc.params[0].type, 1u);
    EXPECT_EQ(ndc.params[0].data, (std::vector<uint8_t>{0x00, 0x00, 0x80, 0x3F}));
    EXPECT_EQ(ndc.params[1].name, "uColor");
    EXPECT_EQ(ndc.params[1].type, 2u);
}

// ─── Test 6: Pipeline state preserved ────────────────────────────────────────
TEST(NormalizerTest, PipelineStatePreserved) {
    gla::Normalizer n;
    gla::store::RawFrame raw{};
    raw.frame_id = 5;

    gla::store::RawDrawCall dc = make_draw_call(1);
    dc.pipeline.viewport[0]    = 0;
    dc.pipeline.viewport[1]    = 0;
    dc.pipeline.viewport[2]    = 1920;
    dc.pipeline.viewport[3]    = 1080;
    dc.pipeline.depth_test     = true;
    dc.pipeline.depth_write    = false;
    dc.pipeline.depth_func     = 0x0203;  // GL_LESS
    dc.pipeline.blend_enabled  = true;
    dc.pipeline.blend_src      = 0x0302;  // GL_SRC_ALPHA
    dc.pipeline.blend_dst      = 0x0303;  // GL_ONE_MINUS_SRC_ALPHA
    dc.pipeline.cull_enabled   = true;
    dc.pipeline.cull_mode      = 0x0405;  // GL_BACK
    dc.pipeline.front_face     = 0x0901;  // GL_CCW
    raw.draw_calls.push_back(std::move(dc));

    gla::NormalizedFrame f = n.normalize(raw);
    const gla::NormalizedPipelineState& ps =
        f.render_passes[0].draw_calls[0].pipeline;

    EXPECT_EQ(ps.viewport[2],    1920);
    EXPECT_EQ(ps.viewport[3],    1080);
    EXPECT_TRUE(ps.depth_test);
    EXPECT_FALSE(ps.depth_write);
    EXPECT_EQ(ps.depth_func,     0x0203u);
    EXPECT_TRUE(ps.blend_enabled);
    EXPECT_EQ(ps.blend_src,      0x0302u);
    EXPECT_EQ(ps.blend_dst,      0x0303u);
    EXPECT_TRUE(ps.cull_enabled);
    EXPECT_EQ(ps.cull_mode,      0x0405u);
    EXPECT_EQ(ps.front_face,     0x0901u);
}

// ─── Test 7: all_draw_calls() convenience accessor ────────────────────────────
TEST(NormalizerTest, AllDrawCallsConvenience) {
    gla::Normalizer n;
    gla::store::RawFrame raw{};
    raw.frame_id = 6;
    for (uint32_t i = 0; i < 5; ++i) {
        raw.draw_calls.push_back(make_draw_call(i));
    }

    gla::NormalizedFrame f = n.normalize(raw);

    // V1 has a single render pass — all_draw_calls() should return 5 entries
    auto all = f.all_draw_calls();
    EXPECT_EQ(all.size(), 5u);

    // Verify the references are valid and ordered
    for (uint32_t i = 0; i < 5; ++i) {
        EXPECT_EQ(all[i].get().id, i);
    }
}
