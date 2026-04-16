#pragma once

namespace gla::ipc {

class ControlSocket {
public:
    ControlSocket() = default;
    ~ControlSocket() = default;
    bool listen(const char *path);
    bool accept_once();
};

} // namespace gla::ipc
