// Control socket — stub
#include "src/core/ipc/control_socket.h"

namespace gla::ipc {

bool ControlSocket::listen(const char *path) { (void)path; return true; }
bool ControlSocket::accept_once() { return true; }

} // namespace gla::ipc
