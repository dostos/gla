// Shared memory ring buffer — POSIX shm + CAS-based slot protocol
#include "src/core/ipc/shm_ring_buffer.h"

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cassert>
#include <cerrno>
#include <cstring>
#include <new>
#include <stdexcept>

namespace gla {

namespace {

// Round `n` up to the nearest multiple of `align` (must be power-of-two).
constexpr size_t align_up(size_t n, size_t align) {
    return (n + align - 1) & ~(align - 1);
}

// Compute total shm size for given parameters.
size_t total_shm_size(uint32_t num_slots, size_t slot_size) {
    // Align slot_size to 64-byte cache line boundary.
    const size_t aligned_slot_data = align_up(slot_size, 64);
    return align_up(sizeof(RingHeader), 64) +
           static_cast<size_t>(num_slots) * (sizeof(SlotHeader) + aligned_slot_data);
}

// Offset of slot_header[i] from base.
size_t slot_header_offset(uint32_t index, uint64_t slot_size) {
    const size_t aligned_slot_data = align_up(static_cast<size_t>(slot_size), 64);
    return align_up(sizeof(RingHeader), 64) +
           static_cast<size_t>(index) * (sizeof(SlotHeader) + aligned_slot_data);
}

// Offset of slot_data[i] from base.
size_t slot_data_offset(uint32_t index, uint64_t slot_size) {
    return slot_header_offset(index, slot_size) + sizeof(SlotHeader);
}

} // namespace

// ── private helpers ───────────────────────────────────────────────────────────

SlotHeader* ShmRingBuffer::slot_header(uint32_t index) const {
    assert(index < num_slots_);
    uint8_t* p = static_cast<uint8_t*>(base_) + slot_header_offset(index, slot_size_);
    return reinterpret_cast<SlotHeader*>(p);
}

void* ShmRingBuffer::slot_data(uint32_t index) const {
    assert(index < num_slots_);
    uint8_t* p = static_cast<uint8_t*>(base_) + slot_data_offset(index, slot_size_);
    return p;
}

// ── create ────────────────────────────────────────────────────────────────────

std::unique_ptr<ShmRingBuffer> ShmRingBuffer::create(
    const std::string& name, uint32_t num_slots, size_t slot_size)
{
    if (num_slots == 0 || slot_size == 0) {
        throw std::invalid_argument("num_slots and slot_size must be non-zero");
    }

    // Unlink any stale segment from a previous crash before re-creating.
    ::shm_unlink(name.c_str()); // ignore error if it doesn't exist

    const int fd = ::shm_open(name.c_str(), O_CREAT | O_RDWR | O_EXCL, 0600);
    if (fd == -1) {
        throw std::runtime_error(std::string("shm_open(create) failed: ") + ::strerror(errno));
    }

    const size_t sz = total_shm_size(num_slots, slot_size);
    if (::ftruncate(fd, static_cast<off_t>(sz)) == -1) {
        const int e = errno;
        ::close(fd);
        ::shm_unlink(name.c_str());
        throw std::runtime_error(std::string("ftruncate failed: ") + ::strerror(e));
    }

    void* base = ::mmap(nullptr, sz, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    ::close(fd); // fd no longer needed after mmap
    if (base == MAP_FAILED) {
        const int e = errno;
        ::shm_unlink(name.c_str());
        throw std::runtime_error(std::string("mmap(create) failed: ") + ::strerror(e));
    }

    // Zero the entire region, then placement-new the atomic fields.
    std::memset(base, 0, sz);

    // Write ring header.
    auto* hdr = new (base) RingHeader{};
    hdr->magic      = GLA_SHM_MAGIC;
    hdr->num_slots  = num_slots;
    hdr->slot_size  = static_cast<uint64_t>(slot_size);
    hdr->total_size = static_cast<uint64_t>(sz);

    // Placement-new each SlotHeader so atomics are properly constructed.
    const size_t aligned_slot_data = align_up(slot_size, 64);
    for (uint32_t i = 0; i < num_slots; ++i) {
        uint8_t* p = static_cast<uint8_t*>(base) +
                     align_up(sizeof(RingHeader), 64) +
                     i * (sizeof(SlotHeader) + aligned_slot_data);
        new (p) SlotHeader{};
    }

    auto rb          = std::unique_ptr<ShmRingBuffer>(new ShmRingBuffer{});
    rb->base_        = base;
    rb->mapped_size_ = sz;
    rb->name_        = name;
    rb->owner_       = true;
    rb->num_slots_   = num_slots;
    rb->slot_size_   = static_cast<uint64_t>(slot_size);
    rb->next_write_  = 0;
    rb->next_read_   = 0;
    return rb;
}

// ── open ──────────────────────────────────────────────────────────────────────

std::unique_ptr<ShmRingBuffer> ShmRingBuffer::open(const std::string& name)
{
    const int fd = ::shm_open(name.c_str(), O_RDWR, 0);
    if (fd == -1) {
        throw std::runtime_error(std::string("shm_open(open) failed: ") + ::strerror(errno));
    }

    // We need to read the header first to know total_size.  Map just the
    // header page, read it, then remap the full region.
    const size_t page = static_cast<size_t>(::sysconf(_SC_PAGESIZE));
    const size_t hdr_map = align_up(sizeof(RingHeader), page);
    void* hdr_base = ::mmap(nullptr, hdr_map, PROT_READ, MAP_SHARED, fd, 0);
    if (hdr_base == MAP_FAILED) {
        const int e = errno;
        ::close(fd);
        throw std::runtime_error(std::string("mmap(header probe) failed: ") + ::strerror(e));
    }

    const auto* hdr = static_cast<const RingHeader*>(hdr_base);
    if (hdr->magic != GLA_SHM_MAGIC) {
        ::munmap(hdr_base, hdr_map);
        ::close(fd);
        throw std::runtime_error("ShmRingBuffer::open: bad magic (not an OpenGPA shm segment)");
    }
    const uint32_t num_slots = hdr->num_slots;
    const uint64_t slot_size = hdr->slot_size;
    const size_t   sz        = static_cast<size_t>(hdr->total_size);
    ::munmap(hdr_base, hdr_map);

    // Now map the full segment read/write.
    void* base = ::mmap(nullptr, sz, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    ::close(fd);
    if (base == MAP_FAILED) {
        throw std::runtime_error(std::string("mmap(full) failed: ") + ::strerror(errno));
    }

    auto rb          = std::unique_ptr<ShmRingBuffer>(new ShmRingBuffer{});
    rb->base_        = base;
    rb->mapped_size_ = sz;
    rb->name_        = name;
    rb->owner_       = false; // client does NOT unlink
    rb->num_slots_   = num_slots;
    rb->slot_size_   = slot_size;
    rb->next_write_  = 0;
    rb->next_read_   = 0;
    return rb;
}

// ── destructor ────────────────────────────────────────────────────────────────

ShmRingBuffer::~ShmRingBuffer() {
    if (base_ && base_ != MAP_FAILED) {
        ::munmap(base_, mapped_size_);
        base_ = nullptr;
    }
    if (owner_) {
        ::shm_unlink(name_.c_str());
    }
}

// ── writer side ───────────────────────────────────────────────────────────────

ShmRingBuffer::WriteSlot ShmRingBuffer::claim_write_slot() {
    // Linear scan starting from the hint position.
    for (uint32_t i = 0; i < num_slots_; ++i) {
        uint32_t idx = (next_write_ + i) % num_slots_;
        SlotHeader* sh = slot_header(idx);

        uint32_t expected = static_cast<uint32_t>(SlotState::FREE);
        const uint32_t desired  = static_cast<uint32_t>(SlotState::WRITING);
        if (sh->state.compare_exchange_strong(
                expected, desired,
                std::memory_order_acquire,
                std::memory_order_relaxed))
        {
            next_write_ = (idx + 1) % num_slots_;
            return WriteSlot{slot_data(idx), idx};
        }
    }
    return WriteSlot{nullptr, 0};
}

void ShmRingBuffer::commit_write(uint32_t index, uint64_t size) {
    assert(index < num_slots_);
    SlotHeader* sh = slot_header(index);
    sh->data_size  = size;
    sh->state.store(static_cast<uint32_t>(SlotState::READY), std::memory_order_release);
}

// ── reader side ───────────────────────────────────────────────────────────────

ShmRingBuffer::ReadSlot ShmRingBuffer::claim_read_slot() {
    for (uint32_t i = 0; i < num_slots_; ++i) {
        uint32_t idx = (next_read_ + i) % num_slots_;
        SlotHeader* sh = slot_header(idx);

        uint32_t expected = static_cast<uint32_t>(SlotState::READY);
        const uint32_t desired  = static_cast<uint32_t>(SlotState::READING);
        if (sh->state.compare_exchange_strong(
                expected, desired,
                std::memory_order_acquire,
                std::memory_order_relaxed))
        {
            next_read_ = (idx + 1) % num_slots_;
            return ReadSlot{slot_data(idx), sh->data_size, idx};
        }
    }
    return ReadSlot{nullptr, 0, 0};
}

void ShmRingBuffer::release_read(uint32_t index) {
    assert(index < num_slots_);
    SlotHeader* sh = slot_header(index);
    sh->state.store(static_cast<uint32_t>(SlotState::FREE), std::memory_order_release);
}

// ── accessors ────────────────────────────────────────────────────────────────

uint32_t ShmRingBuffer::num_slots() const { return num_slots_; }
size_t   ShmRingBuffer::slot_size()  const { return static_cast<size_t>(slot_size_); }

} // namespace gla
