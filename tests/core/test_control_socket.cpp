#include <gtest/gtest.h>
#include "src/core/ipc/control_socket.h"

TEST(ControlSocketTest, Listen) {
    gla::ipc::ControlSocket sock;
    EXPECT_TRUE(sock.listen("/tmp/gla_test.sock"));
}
