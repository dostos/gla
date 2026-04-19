#include <gtest/gtest.h>
#include "src/core/store/frame_store.h"

using gla::store::FrameStore;
using gla::store::RawFrame;
using gla::store::RawDrawCall;

// Helper: make a minimal RawFrame with the given frame_id
static RawFrame make_frame(uint64_t id) {
    RawFrame f{};
    f.frame_id = id;
    f.timestamp = static_cast<double>(id) * 0.016;
    f.api_type = 0;
    return f;
}

// 1. StoreAndRetrieve: store 1 frame, get by ID → matches
TEST(FrameStoreTest, StoreAndRetrieve) {
    FrameStore fs;
    RawFrame f = make_frame(42);
    fs.store(std::move(f));
    const RawFrame* result = fs.get(42);
    ASSERT_NE(result, nullptr);
    EXPECT_EQ(result->frame_id, 42u);
}

// 2. GetLatest: store 3 frames, latest() returns the last one
TEST(FrameStoreTest, GetLatest) {
    FrameStore fs;
    fs.store(make_frame(1));
    fs.store(make_frame(2));
    fs.store(make_frame(3));
    const RawFrame* last = fs.latest();
    ASSERT_NE(last, nullptr);
    EXPECT_EQ(last->frame_id, 3u);
}

// 3. NotFound: get frame_id that doesn't exist → nullptr
TEST(FrameStoreTest, NotFound) {
    FrameStore fs;
    fs.store(make_frame(1));
    EXPECT_EQ(fs.get(999), nullptr);
}

// 4. RingEviction: store 65 frames (capacity 60), first 5 are evicted
TEST(FrameStoreTest, RingEviction) {
    FrameStore fs(60);
    for (uint64_t i = 0; i < 65; ++i) {
        fs.store(make_frame(i));
    }
    // Frames 0–4 should be evicted
    for (uint64_t i = 0; i < 5; ++i) {
        EXPECT_EQ(fs.get(i), nullptr) << "frame " << i << " should be evicted";
    }
    // Frame 5 may or may not be present depending on exact eviction boundary;
    // frames 60–64 must be present
    for (uint64_t i = 5; i < 65; ++i) {
        const RawFrame* f = fs.get(i);
        // Only the last 60 frames survive (IDs 5..64)
        EXPECT_NE(f, nullptr) << "frame " << i << " should still be present";
    }
}

// 5. EmptyStore: latest() returns nullptr, count() == 0
TEST(FrameStoreTest, EmptyStore) {
    FrameStore fs;
    EXPECT_EQ(fs.latest(), nullptr);
    EXPECT_EQ(fs.count(), 0u);
}

// 6. CountTracking: store 3 → count()==3, store 60 more → count()==60 (capped)
TEST(FrameStoreTest, CountTracking) {
    FrameStore fs(60);
    for (uint64_t i = 0; i < 3; ++i) {
        fs.store(make_frame(i));
    }
    EXPECT_EQ(fs.count(), 3u);
    EXPECT_EQ(fs.total_stored(), 3u);

    for (uint64_t i = 3; i < 63; ++i) {
        fs.store(make_frame(i));
    }
    EXPECT_EQ(fs.count(), 60u);
    EXPECT_EQ(fs.total_stored(), 63u);
}

// 7. FrameDataIntegrity: store a frame with draw calls, params, framebuffer
TEST(FrameStoreTest, FrameDataIntegrity) {
    FrameStore fs;

    RawFrame f = make_frame(7);
    f.fb_width = 800;
    f.fb_height = 600;
    f.fb_color.assign(800 * 600 * 4, 0xAB);
    f.fb_depth.assign(800 * 600, 1.0f);
    f.fb_stencil.assign(800 * 600, 0xFF);

    RawDrawCall dc{};
    dc.id = 1;
    dc.primitive_type = 0x0004;  // GL_TRIANGLES
    dc.vertex_count = 3;
    dc.shader_program_id = 42;

    RawDrawCall::Param p;
    p.name = "uColor";
    p.type = 35666;
    p.data = {0x3F, 0x80, 0x00, 0x00};
    dc.params.push_back(p);

    RawDrawCall::Texture tex{};
    tex.slot = 0;
    tex.texture_id = 5;
    tex.width = 256;
    tex.height = 256;
    tex.format = 0x1908;  // GL_RGBA
    dc.textures.push_back(tex);

    dc.pipeline.depth_test = true;
    dc.pipeline.blend_enabled = false;

    dc.vertex_data = {0x01, 0x02, 0x03, 0x04};
    dc.index_data = {0x00, 0x01, 0x02};

    RawDrawCall::VertexAttr attr{0, 0x1406, 3, 12, 0};  // GL_FLOAT, 3 components
    dc.attributes.push_back(attr);

    f.draw_calls.push_back(dc);
    fs.store(std::move(f));

    const RawFrame* stored = fs.get(7);
    ASSERT_NE(stored, nullptr);

    EXPECT_EQ(stored->fb_width, 800u);
    EXPECT_EQ(stored->fb_height, 600u);
    EXPECT_EQ(stored->fb_color.size(), 800u * 600u * 4u);
    EXPECT_EQ(stored->fb_color[0], 0xABu);
    EXPECT_EQ(stored->fb_depth.size(), 800u * 600u);
    EXPECT_FLOAT_EQ(stored->fb_depth[0], 1.0f);
    EXPECT_EQ(stored->fb_stencil.size(), 800u * 600u);
    EXPECT_EQ(stored->fb_stencil[0], 0xFFu);

    ASSERT_EQ(stored->draw_calls.size(), 1u);
    const auto& sdc = stored->draw_calls[0];
    EXPECT_EQ(sdc.id, 1u);
    EXPECT_EQ(sdc.primitive_type, 0x0004u);
    EXPECT_EQ(sdc.vertex_count, 3u);
    EXPECT_EQ(sdc.shader_program_id, 42u);

    ASSERT_EQ(sdc.params.size(), 1u);
    EXPECT_EQ(sdc.params[0].name, "uColor");
    EXPECT_EQ(sdc.params[0].data.size(), 4u);

    ASSERT_EQ(sdc.textures.size(), 1u);
    EXPECT_EQ(sdc.textures[0].texture_id, 5u);
    EXPECT_EQ(sdc.textures[0].width, 256u);

    EXPECT_TRUE(sdc.pipeline.depth_test);
    EXPECT_FALSE(sdc.pipeline.blend_enabled);

    EXPECT_EQ(sdc.vertex_data.size(), 4u);
    EXPECT_EQ(sdc.index_data.size(), 3u);

    ASSERT_EQ(sdc.attributes.size(), 1u);
    EXPECT_EQ(sdc.attributes[0].components, 3u);
}
