// pybind11 bindings for GPA core: Engine, QueryEngine, and supporting types
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "src/core/engine.h"
#include "src/core/normalize/normalizer.h"
#include "src/core/normalize/normalized_types.h"
#include "src/core/query/frame_diff.h"
#include "src/core/query/query_engine.h"
#include "src/core/store/frame_store.h"

namespace py = pybind11;

PYBIND11_MODULE(_gpa_core, m) {
    m.doc() = "GPA core Python bindings";

    // -------------------------------------------------------------------------
    // NormalizedPipelineState
    // -------------------------------------------------------------------------
    py::class_<gpa::NormalizedPipelineState>(m, "NormalizedPipelineState")
        .def_property_readonly("viewport", [](const gpa::NormalizedPipelineState& ps) {
            return py::make_tuple(ps.viewport[0], ps.viewport[1],
                                  ps.viewport[2], ps.viewport[3]);
        })
        .def_property_readonly("scissor", [](const gpa::NormalizedPipelineState& ps) {
            return py::make_tuple(ps.scissor[0], ps.scissor[1],
                                  ps.scissor[2], ps.scissor[3]);
        })
        .def_readonly("scissor_enabled", &gpa::NormalizedPipelineState::scissor_enabled)
        .def_readonly("depth_test",      &gpa::NormalizedPipelineState::depth_test)
        .def_readonly("depth_write",     &gpa::NormalizedPipelineState::depth_write)
        .def_readonly("depth_func",      &gpa::NormalizedPipelineState::depth_func)
        .def_readonly("blend_enabled",   &gpa::NormalizedPipelineState::blend_enabled)
        .def_readonly("blend_src",       &gpa::NormalizedPipelineState::blend_src)
        .def_readonly("blend_dst",       &gpa::NormalizedPipelineState::blend_dst)
        .def_readonly("cull_enabled",    &gpa::NormalizedPipelineState::cull_enabled)
        .def_readonly("cull_mode",       &gpa::NormalizedPipelineState::cull_mode)
        .def_readonly("front_face",      &gpa::NormalizedPipelineState::front_face);

    // -------------------------------------------------------------------------
    // ShaderParameter
    // -------------------------------------------------------------------------
    py::class_<gpa::ShaderParameter>(m, "ShaderParameter")
        .def_readonly("name", &gpa::ShaderParameter::name)
        .def_readonly("type", &gpa::ShaderParameter::type)
        .def_property_readonly("data", [](const gpa::ShaderParameter& sp) {
            return py::bytes(reinterpret_cast<const char*>(sp.data.data()),
                             sp.data.size());
        });

    // -------------------------------------------------------------------------
    // TextureBinding
    // -------------------------------------------------------------------------
    py::class_<gpa::TextureBinding>(m, "TextureBinding")
        .def_readonly("slot",       &gpa::TextureBinding::slot)
        .def_readonly("texture_id", &gpa::TextureBinding::texture_id)
        .def_readonly("width",      &gpa::TextureBinding::width)
        .def_readonly("height",     &gpa::TextureBinding::height)
        .def_readonly("format",     &gpa::TextureBinding::format);

    // -------------------------------------------------------------------------
    // NormalizedDrawCall
    // -------------------------------------------------------------------------
    py::class_<gpa::NormalizedDrawCall>(m, "NormalizedDrawCall")
        .def_readonly("id",             &gpa::NormalizedDrawCall::id)
        .def_readonly("primitive_type", &gpa::NormalizedDrawCall::primitive_type)
        .def_readonly("vertex_count",   &gpa::NormalizedDrawCall::vertex_count)
        .def_readonly("index_count",    &gpa::NormalizedDrawCall::index_count)
        .def_readonly("instance_count", &gpa::NormalizedDrawCall::instance_count)
        .def_readonly("shader_id",      &gpa::NormalizedDrawCall::shader_id)
        .def_readonly("params",         &gpa::NormalizedDrawCall::params)
        .def_readonly("textures",       &gpa::NormalizedDrawCall::textures)
        .def_readonly("pipeline",       &gpa::NormalizedDrawCall::pipeline)
        .def_property_readonly("vertex_data", [](const gpa::NormalizedDrawCall& dc) {
            return py::bytes(reinterpret_cast<const char*>(dc.vertex_data.data()),
                             dc.vertex_data.size());
        })
        .def_property_readonly("index_data", [](const gpa::NormalizedDrawCall& dc) {
            return py::bytes(reinterpret_cast<const char*>(dc.index_data.data()),
                             dc.index_data.size());
        })
        .def_readonly("debug_group_path", &gpa::NormalizedDrawCall::debug_group_path)
        .def_readonly("fbo_color_attachment_tex", &gpa::NormalizedDrawCall::fbo_color_attachment_tex)
        .def_property_readonly("fbo_color_attachments",
            [](const gpa::NormalizedDrawCall& dc) {
                py::list out;
                for (auto v : dc.fbo_color_attachments) out.append(v);
                return out;
            })
        .def_readonly("index_type", &gpa::NormalizedDrawCall::index_type);

    // -------------------------------------------------------------------------
    // DrawCallDiff
    // -------------------------------------------------------------------------
    py::class_<gpa::DrawCallDiff>(m, "DrawCallDiff")
        .def_readonly("dc_id",             &gpa::DrawCallDiff::dc_id)
        .def_readonly("added",             &gpa::DrawCallDiff::added)
        .def_readonly("removed",           &gpa::DrawCallDiff::removed)
        .def_readonly("modified",          &gpa::DrawCallDiff::modified)
        .def_readonly("shader_changed",    &gpa::DrawCallDiff::shader_changed)
        .def_readonly("params_changed",    &gpa::DrawCallDiff::params_changed)
        .def_readonly("pipeline_changed",  &gpa::DrawCallDiff::pipeline_changed)
        .def_readonly("textures_changed",  &gpa::DrawCallDiff::textures_changed)
        .def_readonly("changed_param_names", &gpa::DrawCallDiff::changed_param_names);

    // -------------------------------------------------------------------------
    // PixelDiff
    // -------------------------------------------------------------------------
    py::class_<gpa::PixelDiff>(m, "PixelDiff")
        .def_readonly("x",   &gpa::PixelDiff::x)
        .def_readonly("y",   &gpa::PixelDiff::y)
        .def_readonly("a_r", &gpa::PixelDiff::a_r)
        .def_readonly("a_g", &gpa::PixelDiff::a_g)
        .def_readonly("a_b", &gpa::PixelDiff::a_b)
        .def_readonly("a_a", &gpa::PixelDiff::a_a)
        .def_readonly("b_r", &gpa::PixelDiff::b_r)
        .def_readonly("b_g", &gpa::PixelDiff::b_g)
        .def_readonly("b_b", &gpa::PixelDiff::b_b)
        .def_readonly("b_a", &gpa::PixelDiff::b_a);

    // -------------------------------------------------------------------------
    // FrameDiff
    // -------------------------------------------------------------------------
    py::class_<gpa::FrameDiff>(m, "FrameDiff")
        .def_readonly("frame_id_a",          &gpa::FrameDiff::frame_id_a)
        .def_readonly("frame_id_b",          &gpa::FrameDiff::frame_id_b)
        .def_readonly("draw_calls_added",    &gpa::FrameDiff::draw_calls_added)
        .def_readonly("draw_calls_removed",  &gpa::FrameDiff::draw_calls_removed)
        .def_readonly("draw_calls_modified", &gpa::FrameDiff::draw_calls_modified)
        .def_readonly("draw_calls_unchanged",&gpa::FrameDiff::draw_calls_unchanged)
        .def_readonly("pixels_changed",      &gpa::FrameDiff::pixels_changed)
        .def_readonly("draw_call_diffs",     &gpa::FrameDiff::draw_call_diffs)
        .def_readonly("pixel_diffs",         &gpa::FrameDiff::pixel_diffs);

    // -------------------------------------------------------------------------
    // FrameStore (opaque reference — only exposed so Engine.frame_store() works)
    // -------------------------------------------------------------------------
    py::class_<gpa::store::FrameStore>(m, "FrameStore");

    // -------------------------------------------------------------------------
    // Normalizer
    // -------------------------------------------------------------------------
    py::class_<gpa::Normalizer>(m, "Normalizer")
        .def(py::init<>());

    // -------------------------------------------------------------------------
    // Engine
    // -------------------------------------------------------------------------
    py::class_<gpa::Engine>(m, "Engine")
        .def(py::init<const std::string&, const std::string&, uint32_t, size_t>(),
             py::arg("socket_path"), py::arg("shm_name"),
             py::arg("shm_slots") = 4u,
             py::arg("slot_size") = static_cast<size_t>(64 * 1024 * 1024))
        // run() is blocking — release the GIL so Python threads stay alive
        .def("run",  &gpa::Engine::run,
             py::call_guard<py::gil_scoped_release>())
        .def("stop", &gpa::Engine::stop)
        .def("is_running", &gpa::Engine::is_running)
        .def("is_paused",  &gpa::Engine::is_paused)
        .def("request_pause",  &gpa::Engine::request_pause)
        .def("request_resume", &gpa::Engine::request_resume)
        .def("request_step",   &gpa::Engine::request_step, py::arg("count"))
        // Returns a reference to the internal FrameStore member
        .def("frame_store",
             static_cast<gpa::store::FrameStore& (gpa::Engine::*)()>(
                 &gpa::Engine::frame_store),
             py::return_value_policy::reference_internal);

    // -------------------------------------------------------------------------
    // ClearRecord
    // -------------------------------------------------------------------------
    py::class_<gpa::ClearRecord>(m, "ClearRecord")
        .def_readonly("mask",             &gpa::ClearRecord::mask)
        .def_readonly("draw_call_before", &gpa::ClearRecord::draw_call_before);

    // -------------------------------------------------------------------------
    // QueryEngine::FrameOverview
    // -------------------------------------------------------------------------
    py::class_<gpa::QueryEngine::FrameOverview>(m, "FrameOverview")
        .def_readonly("frame_id",        &gpa::QueryEngine::FrameOverview::frame_id)
        .def_readonly("draw_call_count", &gpa::QueryEngine::FrameOverview::draw_call_count)
        .def_readonly("clear_count",     &gpa::QueryEngine::FrameOverview::clear_count)
        .def_readonly("fb_width",        &gpa::QueryEngine::FrameOverview::fb_width)
        .def_readonly("fb_height",       &gpa::QueryEngine::FrameOverview::fb_height)
        .def_readonly("timestamp",       &gpa::QueryEngine::FrameOverview::timestamp);

    // -------------------------------------------------------------------------
    // QueryEngine::PixelResult
    // -------------------------------------------------------------------------
    py::class_<gpa::QueryEngine::PixelResult>(m, "PixelResult")
        .def_readonly("r",       &gpa::QueryEngine::PixelResult::r)
        .def_readonly("g",       &gpa::QueryEngine::PixelResult::g)
        .def_readonly("b",       &gpa::QueryEngine::PixelResult::b)
        .def_readonly("a",       &gpa::QueryEngine::PixelResult::a)
        .def_readonly("depth",   &gpa::QueryEngine::PixelResult::depth)
        .def_readonly("stencil", &gpa::QueryEngine::PixelResult::stencil);

    // -------------------------------------------------------------------------
    // QueryEngine
    // -------------------------------------------------------------------------
    py::class_<gpa::QueryEngine>(m, "QueryEngine")
        .def(py::init<gpa::store::FrameStore&, gpa::Normalizer&>(),
             py::arg("store"), py::arg("normalizer"),
             // Keep engine (and therefore frame_store) alive for as long as
             // QueryEngine is alive.
             py::keep_alive<1, 2>(),
             py::keep_alive<1, 3>())
        .def("frame_overview",
             &gpa::QueryEngine::frame_overview,
             py::arg("frame_id"))
        .def("latest_frame_overview",
             &gpa::QueryEngine::latest_frame_overview)
        .def("list_draw_calls",
             &gpa::QueryEngine::list_draw_calls,
             py::arg("frame_id"),
             py::arg("limit")  = 50u,
             py::arg("offset") = 0u)
        .def("get_draw_call",
             &gpa::QueryEngine::get_draw_call,
             py::arg("frame_id"), py::arg("dc_id"))
        .def("get_pixel",
             &gpa::QueryEngine::get_pixel,
             py::arg("frame_id"), py::arg("x"), py::arg("y"))
        .def("compare_frames",
             [](const gpa::QueryEngine& qe, uint64_t a, uint64_t b,
                const std::string& depth_str) {
                 gpa::FrameDiffer::DiffDepth depth = gpa::FrameDiffer::DiffDepth::Summary;
                 if (depth_str == "drawcalls") depth = gpa::FrameDiffer::DiffDepth::DrawCalls;
                 else if (depth_str == "pixels") depth = gpa::FrameDiffer::DiffDepth::Pixels;
                 return qe.compare_frames(a, b, depth);
             },
             py::arg("frame_id_a"), py::arg("frame_id_b"),
             py::arg("depth") = std::string("summary"))
        .def("get_normalized_frame",
             [](const gpa::QueryEngine& qe, uint64_t frame_id) -> const gpa::NormalizedFrame* {
                 return qe.get_normalized_frame(frame_id);
             },
             py::arg("frame_id"),
             py::return_value_policy::reference_internal);

    // -------------------------------------------------------------------------
    // NormalizedFrame  (exposes clear_records for diagnostics)
    // -------------------------------------------------------------------------
    py::class_<gpa::NormalizedFrame>(m, "NormalizedFrame")
        .def_readonly("clear_records", &gpa::NormalizedFrame::clear_records);
}
