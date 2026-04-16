// Shared memory ring buffer — stub
#include "src/core/ipc/shm_ring_buffer.h"

namespace gla::ipc {

bool ShmRingBuffer::write(const void *data, size_t len) { (void)data; (void)len; return true; }
bool ShmRingBuffer::read(void *buf, size_t len) { (void)buf; (void)len; return true; }

} // namespace gla::ipc
