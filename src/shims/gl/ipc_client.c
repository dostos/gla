// IPC client — stub
#include "src/shims/gl/ipc_client.h"

int gla_ipc_client_connect(const char *path) { (void)path; return 0; }
void gla_ipc_client_disconnect(void) {}
