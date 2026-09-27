#ifndef INKY_TLS_H
#define INKY_TLS_H
#include <stddef.h>
#include <stdint.h>

typedef struct inky_tls_client inky_tls_client;
enum { INKY_TLS_OK = 0, INKY_TLS_WANT_READ = 1, INKY_TLS_WANT_WRITE = 2, INKY_TLS_CLOSED = 3 };
enum { INKY_TLS_INVALID_ARGUMENT = -100001, INKY_TLS_INVALID_STATE = -100002,
       INKY_TLS_BACKPRESSURE = -100003, INKY_TLS_PIN_MISMATCH = -100004,
       INKY_TLS_ALLOCATION_FAILED = -100005, INKY_TLS_TRUNCATED = -100006 };
enum { INKY_TLS_HANDSHAKING = 0, INKY_TLS_OPEN = 1, INKY_TLS_CLOSING = 2,
       INKY_TLS_CLOSED_STATE = 3, INKY_TLS_FAILED = 4 };

inky_tls_client *inky_tls_create(const char *server_name, const uint8_t *pin,
                                 size_t pin_length, size_t capacity, int *error);
int inky_tls_add_trust_der(inky_tls_client *, const uint8_t *, size_t);
void inky_tls_destroy(inky_tls_client *);
int inky_tls_feed(inky_tls_client *, const uint8_t *, size_t);
int inky_tls_take(inky_tls_client *, uint8_t *, size_t);
int inky_tls_handshake(inky_tls_client *);
int inky_tls_queue_plaintext(inky_tls_client *, const uint8_t *, size_t);
int inky_tls_flush_plaintext(inky_tls_client *);
/* Positive byte count, or -WANT_READ/-WANT_WRITE/-CLOSED, or terminal error. */
int inky_tls_read_plaintext(inky_tls_client *, uint8_t *, size_t);
int inky_tls_close(inky_tls_client *);
void inky_tls_transport_ended(inky_tls_client *);
int inky_tls_state(inky_tls_client *);
size_t inky_tls_pending_plaintext(inky_tls_client *);
size_t inky_tls_receive_capacity(inky_tls_client *);
void inky_tls_error_description(int, char *, size_t);
#endif
