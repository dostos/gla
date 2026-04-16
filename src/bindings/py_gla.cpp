// pybind11 bindings for GLA core: Engine, QueryEngine, and supporting types
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "src/core/engine.h"
#include "src/core/normalize/normalizer.h"
#include "src/core/normalize/normalized_types.h"
#include "src/core/query/query_engine.h"
#include "src/core/store/frame_store.h"

namespace py = pybind11;

PYBIND11_MODULE(_gla_core, m) {
    m.doc() = "GLA core Python bindings";

    // -------------------------------------------------------------------------
    // NormalizedPipelineState
    // -------------------------------------------------------------------------
    py::class_<gla::NormalizedPipelineState>(m, "NormalizedPipelineState")
        .def_property_readonly("viewport", [](const gla::NormalizedPipelineState& ps) {
            return py::make_tuple(ps.viewport[0], ps.viewport[1],
                                  ps.viewport[2], ps.viewport[3]);
        })
        .def_property_readonly("scissor", [](const gla::NormalizedPipelineState& ps) {
            return py::make_tuple(ps.scissor[0], ps.scissor[1],
                                  ps.scissor[2], ps.scissor[3]);
        })
        .def_readonly("scissor_enabled", &gla::NormalizedPipelineState::scissor_enabled)
        .def_readonly("depth_test",      &gla::NormalizedPipelineState::depth_test)
        .def_readonly("depth_write",     &gla::NormalizedPipelineState::depth_write)
        .def_readonly("depth_func",      &gla::NormalizedPipelineState::depth_func)
        .def_readonly("blend_enabled",   &gla::NormalizedPipelineState::blend_enabled)
        .def_readonly("blend_src",       &gla::NormalizedPipelineState::blend_src)
        .def_readonly("blend_dst",       &gla::NormalizedPipelineState::blend_dst)
        .def_readonly("cull_enabled",    &gla::NormalizedPipelineState::cull_enabled)
        .def_readonly("cull_mode",       &gla::NormalizedPipelineState::cull_mode)
        .def_readonly("front_face",      &gla::NormalizedPipelineState::front_face);

    // -------------------------------------------------------------------------
    // ShaderParameter
    // -------------------------------------------------------------------------
    py::class_<gla::ShaderParameter>(m, "ShaderParameter")
        .def_readonly("name", &gla::ShaderParameter::name)
        .def_readonly("type", &gla::ShaderParameter::type)
        .def_property_readonly("data", [](const gla::ShaderParameter& sp) {
            return py::bytes(reinterpret_cast<const char*>(sp.data.data()),
                             sp.data.size());
        });

    // -------------------------------------------------------------------------
    // TextureBinding
    // -------------------------------------------------------------------------
    py::class_<gla::TextureBinding>(m, "TextureBinding")
        .def_readonly("slot",       &gla::TextureBinding::slot)
        .def_readonly("texture_id", &gla::TextureBinding::texture_id)
        .def_readonly("width",      &gla::TextureBinding::width)
        .def_readonly("height",     &gla::TextureBinding::height)
        .def_readonly("format",     &gla::TextureBinding::format);

    // -------------------------------------------------------------------------
    // NormalizedDrawCall
    // -------------------------------------------------------------------------
    py::class_<gla::NormalizedDrawCall>(m, "NormalizedDrawCall")
        .def_readonly("id",             &gla::NormalizedDrawCall::id)
        .def_readonly("primitive_type", &gla::NormalizedDrawCall::primitive_type)
        .def_readonly("vertex_count",   &gla::NormalizedDrawCall::vertex_count)
        .def_readonly("index_count",    &gla::NormalizedDrawCall::index_count)
        .def_readonly("instance_count", &gla::NormalizedDrawCall::instance_count)
        .def_readonly("shader_id",      &gla::NormalizedDrawCall::shader_id)
        .def_readonly("params",         &gla::NormalizedDrawCall::params)
        .def_readonly("textures",       &gla::NormalizedDrawCall::textures)
        .def_readonly("pipeline",       &gla::NormalizedDrawCall::pipeline)
        .def_property_readonly("vertex_data", [](const gla::NormalizedDrawCall& dc) {
            return py::bytes(reinterpret_cast<const char*>(dc.vertex_data.data()),
                             dc.vertex_data.size());
        })
        .def_property_readonly("index_data", [](const gla::NormalizedDrawCall& dc) {
            return py::bytes(reinterpret_cast<const char*>(dc.index_data.data()),
                             dc.index_data.size());
        });

    // -------------------------------------------------------------------------
    // FrameStore (opaque reference — only exposed so Engine.frame_store() works)
    // -------------------------------------------------------------------------
    py::class_<gla::store::FrameStore>(m, "FrameStore");

    // -------------------------------------------------------------------------
    // Normalizer
    // -------------------------------------------------------------------------
    py::class_<gla::Normalizer>(m, "Normalizer")
        .def(py::init<>());

    // -------------------------------------------------------------------------
    // Engine
    // -------------------------------------------------------------------------
    py::class_<gla::Engine>(m, "Engine")
        .def(py::init<const std::string&, const std::string&, uint32_t, size_t>(),
             py::arg("socket_path"), py::arg("shm_name"),
             py::arg("shm_slots") = 4u,
             py::arg("slot_size") = static_cast<size_t>(64 * 1024 * 1024))
        // run() is blocking — release the GIL so Python threads stay alive
        .def("run",  &gla::Engine::run,
             py::call_guard<py::gil_scoped_release>())
        .def("stop", &gla::Engine::stop)
        .def("is_running", &gla::Engine::is_running)
        .def("is_paused",  &gla::Engine::is_paused)
        .def("request_pause",  &gla::Engine::request_pause)
        .def("request_resume", &gla::Engine::request_resume)
        .def("request_step",   &gla::Engine::request_step, py::arg("count"))
        // Returns a reference to the internal FrameStore member
        .def("frame_store",
             static_cast<gla::store::FrameStore& (gla::Engine::*)()>(
                 &gla::Engine::frame_store),
             py::return_value_policy::reference_internal);

    // -------------------------------------------------------------------------
    // QueryEngine::FrameOverview
    // -------------------------------------------------------------------------
    py::class_<gla::QueryEngine::FrameOverview>(m, "FrameOverview")
        .def_readonly("frame_id",        &gla::QueryEngine::FrameOverview::frame_id)
        .def_readonly("draw_call_count", &gla::QueryEngine::FrameOverview::draw_call_count)
        .def_readonly("fb_width",        &gla::QueryEngine::FrameOverview::fb_width)
        .def_readonly("fb_height",       &gla::QueryEngine::FrameOverview::fb_height)
        .def_readonly("timestamp",       &gla::QueryEngine::FrameOverview::timestamp);

    // -------------------------------------------------------------------------
    // QueryEngine::PixelResult
    // -------------------------------------------------------------------------
    py::class_<gla::QueryEngine::PixelResult>(m, "PixelResult")
        .def_readonly("r",       &gla::QueryEngine::PixelResult::r)
        .def_readonly("g",       &gla::QueryEngine::PixelResult::g)
        .def_readonly("b",       &gla::QueryEngine::PixelResult::b)
        .def_readonly("a",       &gla::QueryEngine::PixelResult::a)
        .def_readonly("depth",   &gla::QueryEngine::PixelResult::depth)
        .def_readonly("stencil", &gla::QueryEngine::PixelResult::stencil);

    // -------------------------------------------------------------------------
    // QueryEngine
    // -------------------------------------------------------------------------
    py::class_<gla::QueryEngine>(m, "QueryEngine")
        .def(py::init<gla::store::FrameStore&, gla::Normalizer&>(),
             py::arg("store"), py::arg("normalizer"),
             // Keep engine (and therefore frame_store) alive for as long as
             // QueryEngine is alive.
             py::keep_alive<1, 2>(),
             py::keep_alive<1, 3>())
        .def("frame_overview",
             &gla::QueryEngine::frame_overview,
             py::arg("frame_id"))
        .def("latest_frame_overview",
             &gla::QueryEngine::latest_frame_overview)
        .def("list_draw_calls",
             &gla::QueryEngine::list_draw_calls,
             py::arg("frame_id"),
             py::arg("limit")  = 50u,
             py::arg("offset") = 0u)
        .def("get_draw_call",
             &gla::QueryEngine::get_draw_call,
             py::arg("frame_id"), py::arg("dc_id"))
        .def("get_pixel",
             &gla::QueryEngine::get_pixel,
             py::arg("frame_id"), py::arg("x"), py::arg("y"));
}
