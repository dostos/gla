#include <gtest/gtest.h>
#include "src/core/query/frame_diff.h"
#include "src/core/normalize/normalized_types.h"

// ─── Helpers ──────────────────────────────────────────────────────────────────

static gla::NormalizedDrawCall make_dc(uint32_t id, uint32_t shader_id = 1) {
    gla::NormalizedDrawCall dc{};
    dc.id             = id;
    dc.primitive_type = 0;
    dc.vertex_count   = 3;
    dc.index_count    = 0;
    dc.instance_count = 1;
    dc.shader_id      = shader_id;
    return dc;
}

static gla::NormalizedFrame make_frame(uint64_t id,
                                       std::vector<gla::NormalizedDrawCall> dcs,
                                       uint32_t w = 2, uint32_t h = 2,
                                       std::vector<uint8_t> fb = {}) {
    gla::NormalizedFrame f{};
    f.frame_id  = id;
    f.timestamp = 0.0;
    f.fb_width  = w;
    f.fb_height = h;
    if (!fb.empty()) {
        f.fb_color = std::move(fb);
    } else {
        f.fb_color.assign(w * h * 4, 0);
    }

    gla::RenderPass rp{};
    rp.draw_calls = std::move(dcs);
    f.render_passes.push_back(std::move(rp));
    return f;
}

// ─── Tests ────────────────────────────────────────────────────────────────────

// Test 1: IdenticalFrames — same draw calls → 0 changes
TEST(FrameDiffTest, IdenticalFrames) {
    gla::FrameDiffer differ;

    auto a = make_frame(1, {make_dc(0), make_dc(1), make_dc(2)});
    auto b = make_frame(2, {make_dc(0), make_dc(1), make_dc(2)});

    auto d = differ.diff(a, b);

    EXPECT_EQ(d.draw_calls_added,    0u);
    EXPECT_EQ(d.draw_calls_removed,  0u);
    EXPECT_EQ(d.draw_calls_modified, 0u);
    EXPECT_EQ(d.draw_calls_unchanged,3u);
    EXPECT_EQ(d.pixels_changed,      0u);
    EXPECT_TRUE(d.draw_call_diffs.empty());
}

// Test 2: AddedDrawCall — frame B has one extra draw call → 1 added
TEST(FrameDiffTest, AddedDrawCall) {
    gla::FrameDiffer differ;

    auto a = make_frame(1, {make_dc(0), make_dc(1)});
    auto b = make_frame(2, {make_dc(0), make_dc(1), make_dc(2)});

    auto d = differ.diff(a, b);

    EXPECT_EQ(d.draw_calls_added,    1u);
    EXPECT_EQ(d.draw_calls_removed,  0u);
    EXPECT_EQ(d.draw_calls_modified, 0u);
    EXPECT_EQ(d.draw_calls_unchanged,2u);
}

// Test 3: RemovedDrawCall — frame A has one extra → 1 removed
TEST(FrameDiffTest, RemovedDrawCall) {
    gla::FrameDiffer differ;

    auto a = make_frame(1, {make_dc(0), make_dc(1), make_dc(2)});
    auto b = make_frame(2, {make_dc(0), make_dc(1)});

    auto d = differ.diff(a, b);

    EXPECT_EQ(d.draw_calls_added,    0u);
    EXPECT_EQ(d.draw_calls_removed,  1u);
    EXPECT_EQ(d.draw_calls_modified, 0u);
    EXPECT_EQ(d.draw_calls_unchanged,2u);
}

// Test 4: ModifiedShader — same draw call ID but different shader_id
TEST(FrameDiffTest, ModifiedShader) {
    gla::FrameDiffer differ;

    auto a = make_frame(1, {make_dc(0, /*shader=*/1)});
    auto b = make_frame(2, {make_dc(0, /*shader=*/99)});

    auto d = differ.diff(a, b, gla::FrameDiffer::DiffDepth::DrawCalls);

    EXPECT_EQ(d.draw_calls_modified, 1u);
    ASSERT_EQ(d.draw_call_diffs.size(), 1u);
    const auto& diff0 = d.draw_call_diffs[0];
    EXPECT_EQ(diff0.dc_id, 0u);
    EXPECT_TRUE(diff0.modified);
    EXPECT_TRUE(diff0.shader_changed);
    EXPECT_FALSE(diff0.params_changed);
}

// Test 5: ModifiedParams — same draw call, different uniform value
TEST(FrameDiffTest, ModifiedParams) {
    gla::FrameDiffer differ;

    gla::NormalizedDrawCall dc_a = make_dc(0);
    gla::ShaderParameter pa;
    pa.name = "uColor";
    pa.type = 1;
    pa.data = {0xFF, 0x00, 0x00, 0xFF};
    dc_a.params.push_back(pa);

    gla::NormalizedDrawCall dc_b = make_dc(0);
    gla::ShaderParameter pb;
    pb.name = "uColor";
    pb.type = 1;
    pb.data = {0x00, 0xFF, 0x00, 0xFF};  // different value
    dc_b.params.push_back(pb);

    auto a = make_frame(1, {dc_a});
    auto b = make_frame(2, {dc_b});

    auto d = differ.diff(a, b, gla::FrameDiffer::DiffDepth::DrawCalls);

    EXPECT_EQ(d.draw_calls_modified, 1u);
    ASSERT_EQ(d.draw_call_diffs.size(), 1u);
    const auto& diff0 = d.draw_call_diffs[0];
    EXPECT_TRUE(diff0.params_changed);
    EXPECT_FALSE(diff0.shader_changed);
    ASSERT_EQ(diff0.changed_param_names.size(), 1u);
    EXPECT_EQ(diff0.changed_param_names[0], "uColor");
}

// Test 6: PixelDiff — different framebuffer colors → pixels_changed > 0
TEST(FrameDiffTest, PixelDiff) {
    gla::FrameDiffer differ;

    // 2x2 RGBA all-black
    std::vector<uint8_t> fb_a(2 * 2 * 4, 0);
    // 2x2 RGBA all-white
    std::vector<uint8_t> fb_b(2 * 2 * 4, 0xFF);

    auto a = make_frame(1, {}, 2, 2, fb_a);
    auto b = make_frame(2, {}, 2, 2, fb_b);

    auto d = differ.diff(a, b, gla::FrameDiffer::DiffDepth::Pixels);

    EXPECT_EQ(d.pixels_changed, 4u);  // all 4 pixels differ
    EXPECT_FALSE(d.pixel_diffs.empty());
    EXPECT_EQ(d.pixel_diffs[0].a_r, 0x00);
    EXPECT_EQ(d.pixel_diffs[0].b_r, 0xFF);
}

// Test 7: DiffDepthSummary — draw_call_diffs is empty even when there are diffs
TEST(FrameDiffTest, DiffDepthSummary) {
    gla::FrameDiffer differ;

    auto a = make_frame(1, {make_dc(0), make_dc(1)});
    auto b = make_frame(2, {make_dc(0), make_dc(2)});  // dc 1 removed, dc 2 added

    auto d = differ.diff(a, b, gla::FrameDiffer::DiffDepth::Summary);

    EXPECT_EQ(d.draw_calls_added,   1u);
    EXPECT_EQ(d.draw_calls_removed, 1u);
    // At Summary depth: no detailed diffs
    EXPECT_TRUE(d.draw_call_diffs.empty());
    EXPECT_TRUE(d.pixel_diffs.empty());
}

// Test 8: DiffDepthPixels — pixel_diffs is populated
TEST(FrameDiffTest, DiffDepthPixels) {
    gla::FrameDiffer differ;

    std::vector<uint8_t> fb_a(4 * 4 * 4, 0x00);
    std::vector<uint8_t> fb_b(4 * 4 * 4, 0x00);
    // Make one pixel differ: pixel (1,1), index = 1*4+1 = 5
    fb_b[5 * 4 + 0] = 0xAB;

    auto a = make_frame(1, {}, 4, 4, fb_a);
    auto b = make_frame(2, {}, 4, 4, fb_b);

    auto d = differ.diff(a, b, gla::FrameDiffer::DiffDepth::Pixels, 100);

    EXPECT_EQ(d.pixels_changed, 1u);
    ASSERT_EQ(d.pixel_diffs.size(), 1u);
    EXPECT_EQ(d.pixel_diffs[0].x, 1u);
    EXPECT_EQ(d.pixel_diffs[0].y, 1u);
    EXPECT_EQ(d.pixel_diffs[0].b_r, 0xAB);
}
