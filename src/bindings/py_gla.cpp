// pybind11 bindings — stub
#include <pybind11/pybind11.h>

namespace py = pybind11;

PYBIND11_MODULE(_gla_core, m) {
    m.doc() = "GLA core Python bindings (stub)";
    m.def("version", []() { return "0.0.1"; });
}
