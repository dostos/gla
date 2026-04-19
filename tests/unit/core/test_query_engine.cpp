#include <gtest/gtest.h>
#include "src/core/query/query_engine.h"
#include "src/core/normalize/normalizer.h"
#include "src/core/store/frame_store.h"
#include "src/core/store/raw_frame.h"

// ─── Helpers ──────────────────────────────────────────────────────────────────

static gla::store::RawDrawCall make_dc(uint32_t id) {
    gla::store::RawDrawCall dc{};
    dc.id               = id;
    dc.primitive_type   = 4;   // GL_TRIANGLES
    dc.vertex_count     = 3;
    dc.index_count      = 0;
    dc.instance_count   = 1;
    dc.shader_program_id = 1;
    dc.pipeline         = {};
    return dc;
}

static gla::store::RawFrame make_frame(uint64_t id, uint32_t num_dc,
                                       uint32_t w = 800, uint32_t h = 600,
                                       double ts = 1.0) {
    gla::store::RawFrame f{};
    f.frame_id  = id;
    f.timestamp = ts;
    f.api_type  = 0;
    f.fb_width  = w;
    f.fb_height = h;
    for (uint32_t i = 0; i < num_dc; ++i) {
        f.draw_calls.push_back(make_dc(i));
    }
    return f;
}

// ─── Tests ────────────────────────────────────────────────────────────────────

// Test 1: FrameOverview
TEST(QueryEngineTest, FrameOverview) {
    gla::store::FrameStore store;
    gla::Normalizer norm;
    gla::QueryEngine qe(store, norm);

    store.store(make_frame(1, 3, 800, 600, 2.5));

    auto ov = qe.frame_overview(1);
    ASSERT_TRUE(ov.has_value());
    EXPECT_EQ(ov->frame_id,        1u);
    EXPECT_EQ(ov->draw_call_count, 3u);
    EXPECT_EQ(ov->fb_width,        800u);
    EXPECT_EQ(ov->fb_height,       600u);
    EXPECT_DOUBLE_EQ(ov->timestamp, 2.5);
}

// Test 2: LatestFrameOverview
TEST(QueryEngineTest, LatestFrameOverview) {
    gla::store::FrameStore store;
    gla::Normalizer norm;
    gla::QueryEngine qe(store, norm);

    store.store(make_frame(10, 1, 640, 480, 0.1));
    store.store(make_frame(11, 2, 1920, 1080, 0.2));

    auto ov = qe.latest_frame_overview();
    ASSERT_TRUE(ov.has_value());
    EXPECT_EQ(ov->frame_id, 11u);
    EXPECT_EQ(ov->draw_call_count, 2u);
    EXPECT_EQ(ov->fb_width, 1920u);
    EXPECT_EQ(ov->fb_height, 1080u);
}

// Test 3: FrameNotFound
TEST(QueryEngineTest, FrameNotFound) {
    gla::store::FrameStore store;
    gla::Normalizer norm;
    gla::QueryEngine qe(store, norm);

    EXPECT_FALSE(qe.frame_overview(999).has_value());
    EXPECT_FALSE(qe.latest_frame_overview().has_value());
}

// Test 4: ListDrawCallsPaginated
TEST(QueryEngineTest, ListDrawCallsPaginated) {
    gla::store::FrameStore store;
    gla::Normalizer norm;
    gla::QueryEngine qe(store, norm);

    // 5 draw calls with IDs 0..4
    store.store(make_frame(1, 5));

    // offset=1, limit=2 → draw calls with IDs 1 and 2
    auto dcs = qe.list_draw_calls(1, 2, 1);
    ASSERT_EQ(dcs.size(), 2u);
    EXPECT_EQ(dcs[0].id, 1u);
    EXPECT_EQ(dcs[1].id, 2u);
}

// Test 5: GetDrawCallById
TEST(QueryEngineTest, GetDrawCallById) {
    gla::store::FrameStore store;
    gla::Normalizer norm;
    gla::QueryEngine qe(store, norm);

    store.store(make_frame(1, 5));

    auto dc = qe.get_draw_call(1, 3);
    ASSERT_TRUE(dc.has_value());
    EXPECT_EQ(dc->id, 3u);
    EXPECT_EQ(dc->vertex_count, 3u);
}

// Test 6: GetDrawCallNotFound
TEST(QueryEngineTest, GetDrawCallNotFound) {
    gla::store::FrameStore store;
    gla::Normalizer norm;
    gla::QueryEngine qe(store, norm);

    store.store(make_frame(1, 3));

    EXPECT_FALSE(qe.get_draw_call(1, 99).has_value());
    EXPECT_FALSE(qe.get_draw_call(999, 0).has_value());
}

// Test 7: GetPixel
TEST(QueryEngineTest, GetPixel) {
    gla::store::FrameStore store;
    gla::Normalizer norm;
    gla::QueryEngine qe(store, norm);

    gla::store::RawFrame f = make_frame(1, 0, 4, 3, 0.0);
    // 4*3=12 pixels, RGBA
    f.fb_color.resize(4 * 3 * 4, 0);
    f.fb_depth.resize(4 * 3, 0.0f);
    f.fb_stencil.resize(4 * 3, 0);

    // Set pixel (2, 1): index = 1*4 + 2 = 6
    uint32_t idx = 1 * 4 + 2;
    f.fb_color[idx * 4 + 0] = 0xDE;  // R
    f.fb_color[idx * 4 + 1] = 0xAD;  // G
    f.fb_color[idx * 4 + 2] = 0xBE;  // B
    f.fb_color[idx * 4 + 3] = 0xEF;  // A
    f.fb_depth[idx]          = 0.75f;
    f.fb_stencil[idx]        = 0x05;

    store.store(std::move(f));

    auto px = qe.get_pixel(1, 2, 1);
    ASSERT_TRUE(px.has_value());
    EXPECT_EQ(px->r,       0xDE);
    EXPECT_EQ(px->g,       0xAD);
    EXPECT_EQ(px->b,       0xBE);
    EXPECT_EQ(px->a,       0xEF);
    EXPECT_FLOAT_EQ(px->depth,  0.75f);
    EXPECT_EQ(px->stencil, 0x05);
}

// Test 8: GetPixelOutOfBounds
TEST(QueryEngineTest, GetPixelOutOfBounds) {
    gla::store::FrameStore store;
    gla::Normalizer norm;
    gla::QueryEngine qe(store, norm);

    gla::store::RawFrame f = make_frame(1, 0, 4, 3, 0.0);
    f.fb_color.resize(4 * 3 * 4, 0xFF);
    f.fb_depth.resize(4 * 3, 1.0f);
    store.store(std::move(f));

    EXPECT_FALSE(qe.get_pixel(1, 4, 0).has_value());   // x == width
    EXPECT_FALSE(qe.get_pixel(1, 0, 3).has_value());   // y == height
    EXPECT_FALSE(qe.get_pixel(1, 10, 10).has_value()); // both out
}

// Test 9: CacheWorks — query same frame twice, normalization happens once.
// We verify this by wrapping Normalizer calls via a counting subclass.
namespace {
class CountingNormalizer : public gla::Normalizer {
public:
    mutable int call_count = 0;

    gla::NormalizedFrame normalize(const gla::store::RawFrame& raw) const {
        ++call_count;
        return gla::Normalizer::normalize(raw);
    }
};
}  // namespace

TEST(QueryEngineTest, CacheWorks) {
    gla::store::FrameStore store;
    CountingNormalizer norm;
    gla::QueryEngine qe(store, norm);

    store.store(make_frame(1, 2));

    // First query → normalizes
    auto ov1 = qe.frame_overview(1);
    ASSERT_TRUE(ov1.has_value());
    EXPECT_EQ(norm.call_count, 1);

    // Second query → uses cache, no additional normalization
    auto ov2 = qe.frame_overview(1);
    ASSERT_TRUE(ov2.has_value());
    EXPECT_EQ(norm.call_count, 1);

    // draw call query on same frame → still cached
    qe.list_draw_calls(1);
    EXPECT_EQ(norm.call_count, 1);
}
