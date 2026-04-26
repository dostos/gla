/* Unit tests for the IPC connect-with-backoff retry loop in
 * src/shims/gl/ipc_client.c.
 *
 * Background: under high parallel load (R10v2+R11 ran 33 with_gpa scenarios
 * in parallel, 24/33 hit "[OpenGPA] handshake send failed") the original
 * single-shot connect() to the engine's Unix socket would fail under kernel
 * socket-backlog pressure with no recovery. We added a backoff retry loop
 * around connect()+handshake. These tests pin down its behavior:
 *
 *   1. Listener up before client → succeeds on first attempt.
 *   2. Listener delays accept by ~150 ms → client retries past the first
 *      two failed connects (ENOENT before bind, ECONNREFUSED before listen)
 *      and succeeds by attempt 3.
 *   3. No listener at all → client returns -1 after ~750 ms total
 *      (4 sleeps × 50/100/200/400 ms) without crashing.
 *   4. Intermediate failures emit no log lines; only one stderr line on
 *      exhaustion ("[OpenGPA] handshake failed after 5 retries; ...").
 *
 * Uses assert() — no external test framework. Mirrors the tiny TCP-listener
 * pattern in test_http_post.c, but speaks AF_UNIX + the GPA wire protocol
 * (length-prefixed messages, MSG_HANDSHAKE / MSG_HANDSHAKE_OK).
 */

#define _GNU_SOURCE
#include "src/shims/gl/ipc_client.h"

#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

/* ------------------------------------------------------------------------
 * Wire protocol mirror (kept in sync with ipc_client.c)
 * ------------------------------------------------------------------------ */

#define MSG_HANDSHAKE    1u
#define MSG_HANDSHAKE_OK 2u

/* ------------------------------------------------------------------------
 * Helpers — temp socket path + millisecond clock
 * ------------------------------------------------------------------------ */

static void make_socket_path(char* out, size_t cap, const char* tag) {
    /* /tmp/gpa-ipc-test-<pid>-<tag>.sock — short enough to fit in
     * sun_path (108 bytes) on every Linux. */
    snprintf(out, cap, "/tmp/gpa-ipc-test-%d-%s.sock", (int)getpid(), tag);
    unlink(out);  /* clean any leftover */
}

static long long now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

/* ------------------------------------------------------------------------
 * Fake server — answers one handshake on an AF_UNIX socket
 * ------------------------------------------------------------------------ */

typedef struct {
    char    path[128];
    int     listen_delay_ms;     /* ms to sleep BEFORE bind+listen */
    int     accept_delay_ms;     /* ms to sleep AFTER bind, BEFORE accept */
    int     ready;               /* set once thread is running */
    int     bound;               /* set once bind+listen has happened */
    int     handled;             /* set once one client got HANDSHAKE_OK */
    int     handshakes_seen;     /* total HANDSHAKE messages received */
} FakeServer;

static int recv_all_n(int fd, void* buf, size_t len) {
    uint8_t* p = (uint8_t*)buf;
    while (len > 0) {
        ssize_t n = recv(fd, p, len, 0);
        if (n <= 0) return -1;
        p   += n;
        len -= (size_t)n;
    }
    return 0;
}

static int send_all_n(int fd, const void* buf, size_t len) {
    const uint8_t* p = (const uint8_t*)buf;
    while (len > 0) {
        ssize_t n = send(fd, p, len, MSG_NOSIGNAL);
        if (n <= 0) return -1;
        p   += n;
        len -= (size_t)n;
    }
    return 0;
}

static void serve_one_handshake(int cs, FakeServer* S) {
    /* Read [BE-uint32 length][type byte][12-byte HandshakePayload]. */
    uint32_t length_be = 0;
    if (recv_all_n(cs, &length_be, 4) != 0) return;
    uint8_t type = 0;
    if (recv_all_n(cs, &type, 1) != 0) return;
    uint32_t body_len = ntohl(length_be) - 1;
    /* Drain payload (12 bytes for HandshakePayload, but be tolerant). */
    uint8_t scratch[64];
    while (body_len > 0) {
        size_t want = body_len < sizeof(scratch) ? body_len : sizeof(scratch);
        if (recv_all_n(cs, scratch, want) != 0) return;
        body_len -= (uint32_t)want;
    }
    if (type != MSG_HANDSHAKE) return;
    S->handshakes_seen++;
    /* Reply HANDSHAKE_OK. */
    uint32_t len_be = htonl(1);  /* type byte only */
    uint8_t  ok     = MSG_HANDSHAKE_OK;
    if (send_all_n(cs, &len_be, 4) != 0) return;
    if (send_all_n(cs, &ok,      1) != 0) return;
    S->handled++;
}

static void* fake_server_thread(void* arg) {
    FakeServer* S = (FakeServer*)arg;
    S->ready = 1;

    if (S->listen_delay_ms > 0) {
        usleep((useconds_t)S->listen_delay_ms * 1000);
    }

    int ls = socket(AF_UNIX, SOCK_STREAM, 0);
    if (ls < 0) return NULL;

    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, S->path, sizeof(addr.sun_path) - 1);

    if (bind(ls, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("fake bind");
        close(ls);
        return NULL;
    }
    if (listen(ls, 8) < 0) {
        perror("fake listen");
        close(ls);
        return NULL;
    }
    S->bound = 1;

    if (S->accept_delay_ms > 0) {
        usleep((useconds_t)S->accept_delay_ms * 1000);
    }

    /* Accept until the client gives up; serve any handshakes that arrive.
     * We use a select() with a 3 s ceiling so the test thread can't hang
     * forever if something pathological happens. */
    fd_set rfds;
    FD_ZERO(&rfds);
    FD_SET(ls, &rfds);
    struct timeval tv = {3, 0};
    if (select(ls + 1, &rfds, NULL, NULL, &tv) > 0) {
        int cs = accept(ls, NULL, NULL);
        if (cs >= 0) {
            serve_one_handshake(cs, S);
            close(cs);
        }
    }

    close(ls);
    unlink(S->path);
    return NULL;
}

/* ------------------------------------------------------------------------
 * stderr-capture helper — used by the no-spam test
 * ------------------------------------------------------------------------ */

static int capture_stderr_to(int* saved_fd, int* read_fd) {
    int pipefd[2];
    if (pipe(pipefd) < 0) return -1;
    /* Make the read end non-blocking so we can drain after the fact
     * without risk of hanging. */
    int flags = fcntl(pipefd[0], F_GETFL, 0);
    fcntl(pipefd[0], F_SETFL, flags | O_NONBLOCK);

    fflush(stderr);
    *saved_fd = dup(STDERR_FILENO);
    if (dup2(pipefd[1], STDERR_FILENO) < 0) {
        close(pipefd[0]);
        close(pipefd[1]);
        return -1;
    }
    close(pipefd[1]);  /* keep only the read end for ourselves */
    *read_fd = pipefd[0];
    return 0;
}

static int restore_stderr(int saved_fd, int read_fd, char* out, size_t cap) {
    fflush(stderr);
    dup2(saved_fd, STDERR_FILENO);
    close(saved_fd);
    /* Drain whatever was buffered — pipe buffer is plenty (64 KiB+) so
     * we don't worry about overflow for a handful of log lines. */
    size_t off = 0;
    while (off + 1 < cap) {
        ssize_t n = read(read_fd, out + off, cap - 1 - off);
        if (n <= 0) break;
        off += (size_t)n;
    }
    out[off] = '\0';
    close(read_fd);
    return (int)off;
}

/* ------------------------------------------------------------------------
 * Tests
 * ------------------------------------------------------------------------ */

static void test_connect_succeeds_on_first_try(void) {
    FakeServer S = {0};
    make_socket_path(S.path, sizeof(S.path), "first");

    pthread_t tid;
    pthread_create(&tid, NULL, fake_server_thread, &S);
    /* Wait for thread to bind+listen so the client's first connect() is
     * guaranteed to succeed. */
    while (!S.bound) { usleep(1000); }

    long long t0 = now_ms();
    int rc = gpa_ipc_connect_socket_with_retry(S.path);
    long long elapsed = now_ms() - t0;

    pthread_join(tid, NULL);

    assert(rc == 0);
    assert(S.handshakes_seen == 1);
    /* No backoff sleeps should have fired — well under the first 50 ms
     * delay. Allow generous slack for slow CI. */
    assert(elapsed < 50);
    printf("PASS test_connect_succeeds_on_first_try (%lld ms)\n", elapsed);
}

static void test_connect_succeeds_on_third_try(void) {
    FakeServer S = {0};
    make_socket_path(S.path, sizeof(S.path), "third");
    /* Don't bind for 150 ms. Client schedule: attempt 0 fails immediately
     * (ENOENT, no socket file), sleep 50, attempt 1 fails (still no file),
     * sleep 100, attempt 2 starts at t≈150 ms — by which point the
     * server has bound and is accepting. */
    S.listen_delay_ms = 150;

    pthread_t tid;
    pthread_create(&tid, NULL, fake_server_thread, &S);
    while (!S.ready) { usleep(1000); }

    long long t0 = now_ms();
    int rc = gpa_ipc_connect_socket_with_retry(S.path);
    long long elapsed = now_ms() - t0;

    pthread_join(tid, NULL);

    assert(rc == 0);
    assert(S.handshakes_seen == 1);
    /* Must have slept at least the first two delays = 150 ms before
     * succeeding. Upper bound: under 1 s — well short of full exhaustion. */
    assert(elapsed >= 140);   /* slack for clock granularity */
    assert(elapsed < 1000);
    printf("PASS test_connect_succeeds_on_third_try (%lld ms)\n", elapsed);
}

static void test_connect_exhausts_retries(void) {
    char path[128];
    make_socket_path(path, sizeof(path), "none");
    /* No listener at all — every connect() should fail with ENOENT. */

    long long t0 = now_ms();
    int rc = gpa_ipc_connect_socket_with_retry(path);
    long long elapsed = now_ms() - t0;

    assert(rc == -1);
    /* Schedule: 4 sleeps between 5 attempts = 50+100+200+400 = 750 ms.
     * Generous slack on both ends — the connect()s themselves are fast
     * (ENOENT is immediate) but scheduler jitter can add tens of ms. */
    assert(elapsed >= 700);
    assert(elapsed < 2000);   /* the documented 2 s ceiling */
    printf("PASS test_connect_exhausts_retries (%lld ms)\n", elapsed);
}

static void test_no_logs_on_intermediate_failures(void) {
    char path[128];
    make_socket_path(path, sizeof(path), "silent");

    int saved_fd, read_fd;
    if (capture_stderr_to(&saved_fd, &read_fd) != 0) {
        fprintf(stderr, "stderr capture setup failed — skipping\n");
        return;
    }

    int rc = gpa_ipc_connect_socket_with_retry(path);

    char captured[2048];
    int  captured_len = restore_stderr(saved_fd, read_fd, captured, sizeof(captured));

    assert(rc == -1);
    /* Exactly one log line on exhaustion. We don't pin its exact text
     * beyond the prefix + ratio, to allow future wording tweaks. */
    int newlines = 0;
    for (int i = 0; i < captured_len; i++) {
        if (captured[i] == '\n') newlines++;
    }
    assert(newlines == 1);
    assert(strstr(captured, "[OpenGPA]") != NULL);
    assert(strstr(captured, "handshake failed") != NULL);
    assert(strstr(captured, "5 retries") != NULL);
    /* Must NOT contain per-attempt failure spam. */
    assert(strstr(captured, "connect(") == NULL);
    assert(strstr(captured, "handshake send failed") == NULL);
    printf("PASS test_no_logs_on_intermediate_failures (one line: %.*s)\n",
           captured_len > 0 ? captured_len - 1 : 0, captured);
}

int main(void) {
    test_connect_succeeds_on_first_try();
    test_connect_succeeds_on_third_try();
    test_connect_exhausts_retries();
    test_no_logs_on_intermediate_failures();
    printf("All ipc_retry tests passed.\n");
    return 0;
}
