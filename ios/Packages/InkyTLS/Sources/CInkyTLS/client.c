#include "CInkyTLS.h"
#include <MbedTLS.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>

#define MAX_PLAINTEXT 16384
#define MAX_CERTIFICATE 65536
/* Also serializes process-global PSA state when distinct Swift actors run in parallel. */
static pthread_mutex_t library_lock = PTHREAD_MUTEX_INITIALIZER;
static int crypto_initialized = 0;
#define LOCK() pthread_mutex_lock(&library_lock)
#define RETURN(value) do { int result_ = (value); pthread_mutex_unlock(&library_lock); return result_; } while (0)

typedef struct { uint8_t *bytes; size_t capacity, start, count; } ring;
struct inky_tls_client {
    mbedtls_ssl_context ssl;
    mbedtls_ssl_config config;
    mbedtls_x509_crt trust;
    ring input, output;
    uint8_t pin[32], pending[MAX_PLAINTEXT];
    size_t pending_length, pending_offset;
    unsigned anchors;
    int state, started, pin_seen, pin_rejected, transport_ended, peer_closed, close_sent, error;
};

static void push(ring *r, const uint8_t *data, size_t count) {
    size_t end = (r->start + r->count) % r->capacity;
    size_t first = count < r->capacity - end ? count : r->capacity - end;
    memcpy(r->bytes + end, data, first);
    if (count > first) memcpy(r->bytes, data + first, count - first);
    r->count += count;
}
static size_t pop(ring *r, uint8_t *data, size_t count) {
    if (count > r->count) count = r->count;
    size_t first = count < r->capacity - r->start ? count : r->capacity - r->start;
    memcpy(data, r->bytes + r->start, first);
    if (count > first) memcpy(data + first, r->bytes, count - first);
    r->start = (r->start + count) % r->capacity; r->count -= count;
    return count;
}
static int send_bytes(void *opaque, const unsigned char *data, size_t count) {
    inky_tls_client *c = opaque;
    size_t available = c->output.capacity - c->output.count;
    if (!available) return MBEDTLS_ERR_SSL_WANT_WRITE;
    if (count > available) count = available;
    push(&c->output, data, count); return (int)count;
}
static int receive_bytes(void *opaque, unsigned char *data, size_t count) {
    inky_tls_client *c = opaque;
    if (!c->input.count) return c->transport_ended ? 0 : MBEDTLS_ERR_SSL_WANT_READ;
    return (int)pop(&c->input, data, count);
}
static int verify_pin(void *opaque, mbedtls_x509_crt *certificate, int depth, uint32_t *flags) {
    inky_tls_client *c = opaque;
    if (depth != 0) return 0;
    uint8_t der[2048], digest[32]; size_t written = 0;
    int length = mbedtls_pk_write_pubkey_der(&certificate->pk, der, sizeof(der));
    int matches = length > 0 && psa_hash_compute(PSA_ALG_SHA_256,
        der + sizeof(der) - length, (size_t)length, digest, sizeof(digest), &written) == PSA_SUCCESS;
    if (!matches || written != 32 || memcmp(digest, c->pin, 32)) {
        c->pin_rejected = 1;
        *flags |= MBEDTLS_X509_BADCERT_OTHER;
    } else c->pin_seen = 1;
    /* Never clear chain, hostname, expiry or any other X.509 verification error. */
    return 0;
}
static void destroy_unlocked(inky_tls_client *c) {
    if (!c) return;
    mbedtls_ssl_free(&c->ssl); mbedtls_ssl_config_free(&c->config);
    mbedtls_x509_crt_free(&c->trust);
    if (c->input.bytes) { mbedtls_platform_zeroize(c->input.bytes, c->input.capacity); free(c->input.bytes); }
    if (c->output.bytes) { mbedtls_platform_zeroize(c->output.bytes, c->output.capacity); free(c->output.bytes); }
    mbedtls_platform_zeroize(c, sizeof(*c)); free(c);
}
static int fail(inky_tls_client *c, int code) {
    c->state = INKY_TLS_FAILED; c->error = code;
    mbedtls_platform_zeroize(c->pending, sizeof(c->pending));
    c->pending_length = c->pending_offset = 0;
    return code;
}
static int progress(inky_tls_client *c, int result) {
    if (result == MBEDTLS_ERR_SSL_WANT_READ) return INKY_TLS_WANT_READ;
    if (result == MBEDTLS_ERR_SSL_WANT_WRITE) return INKY_TLS_WANT_WRITE;
    return result < 0 ? fail(c, c->pin_rejected ? INKY_TLS_PIN_MISMATCH : result) : INKY_TLS_OK;
}

inky_tls_client *inky_tls_create(const char *name, const uint8_t *pin,
                                 size_t pin_length, size_t capacity, int *error) {
    if (!error) return NULL;
    *error = INKY_TLS_INVALID_ARGUMENT;
    if (!name || !name[0] || strlen(name) > 253 || !pin || pin_length != 32 ||
        capacity < 1024 || capacity > 262144) return NULL;
    LOCK();
    inky_tls_client *c = calloc(1, sizeof(*c));
    if (!c) { *error = INKY_TLS_ALLOCATION_FAILED; pthread_mutex_unlock(&library_lock); return NULL; }
    mbedtls_ssl_init(&c->ssl); mbedtls_ssl_config_init(&c->config); mbedtls_x509_crt_init(&c->trust);
    c->input.capacity = c->output.capacity = capacity;
    c->input.bytes = calloc(1, capacity); c->output.bytes = calloc(1, capacity);
    int result = INKY_TLS_ALLOCATION_FAILED;
    if (!c->input.bytes || !c->output.bytes) goto failed;
    if (!crypto_initialized) {
        result = (int)psa_crypto_init();
        if (result) goto failed;
        crypto_initialized = 1;
    }
    memcpy(c->pin, pin, 32);
    result = mbedtls_ssl_config_defaults(&c->config, MBEDTLS_SSL_IS_CLIENT,
        MBEDTLS_SSL_TRANSPORT_STREAM, MBEDTLS_SSL_PRESET_DEFAULT);
    if (result) goto failed;
    mbedtls_ssl_conf_min_tls_version(&c->config, MBEDTLS_SSL_VERSION_TLS1_3);
    mbedtls_ssl_conf_max_tls_version(&c->config, MBEDTLS_SSL_VERSION_TLS1_3);
    mbedtls_ssl_conf_authmode(&c->config, MBEDTLS_SSL_VERIFY_REQUIRED);
    mbedtls_ssl_conf_ca_chain(&c->config, &c->trust, NULL);
    mbedtls_ssl_conf_verify(&c->config, verify_pin, c);
#if defined(MBEDTLS_SSL_SESSION_TICKETS)
    mbedtls_ssl_conf_session_tickets(&c->config, MBEDTLS_SSL_SESSION_TICKETS_DISABLED);
#endif
#if defined(MBEDTLS_SSL_EARLY_DATA)
    mbedtls_ssl_conf_early_data(&c->config, MBEDTLS_SSL_EARLY_DATA_DISABLED);
#endif
    result = mbedtls_ssl_setup(&c->ssl, &c->config);
    if (result) goto failed;
    result = mbedtls_ssl_set_hostname(&c->ssl, name);
    if (result) goto failed;
    mbedtls_ssl_set_bio(&c->ssl, c, send_bytes, receive_bytes, NULL);
    *error = 0; pthread_mutex_unlock(&library_lock); return c;
failed:
    *error = result; destroy_unlocked(c); pthread_mutex_unlock(&library_lock); return NULL;
}
int inky_tls_add_trust_der(inky_tls_client *c, const uint8_t *der, size_t length) {
    LOCK();
    if (!c || !der || !length || length > MAX_CERTIFICATE) RETURN(INKY_TLS_INVALID_ARGUMENT);
    if (c->started || c->state != INKY_TLS_HANDSHAKING || c->anchors >= 8) RETURN(INKY_TLS_INVALID_STATE);
    int result = mbedtls_x509_crt_parse_der(&c->trust, der, length);
    if (!result) c->anchors++;
    RETURN(result);
}
void inky_tls_destroy(inky_tls_client *c) { LOCK(); destroy_unlocked(c); pthread_mutex_unlock(&library_lock); }
int inky_tls_feed(inky_tls_client *c, const uint8_t *data, size_t count) {
    LOCK();
    if (!c || (!data && count)) RETURN(INKY_TLS_INVALID_ARGUMENT);
    if (c->state >= INKY_TLS_CLOSED_STATE || c->transport_ended) RETURN(INKY_TLS_INVALID_STATE);
    if (count > c->input.capacity - c->input.count) RETURN(INKY_TLS_BACKPRESSURE);
    if (count) push(&c->input, data, count);
    RETURN(INKY_TLS_OK);
}
int inky_tls_take(inky_tls_client *c, uint8_t *data, size_t count) {
    LOCK();
    if (!c || !data || !count || count > 262144) RETURN(INKY_TLS_INVALID_ARGUMENT);
    RETURN((int)pop(&c->output, data, count));
}
int inky_tls_handshake(inky_tls_client *c) {
    LOCK();
    if (!c) RETURN(INKY_TLS_INVALID_ARGUMENT);
    if (c->state == INKY_TLS_FAILED) RETURN(c->error);
    if (c->state == INKY_TLS_OPEN) RETURN(INKY_TLS_OK);
    if (c->state != INKY_TLS_HANDSHAKING || !c->anchors) RETURN(INKY_TLS_INVALID_STATE);
    c->started = 1;
    int result = mbedtls_ssl_handshake(&c->ssl);
    if (!result) {
        if (!c->pin_seen || c->pin_rejected || mbedtls_ssl_get_verify_result(&c->ssl))
            RETURN(fail(c, INKY_TLS_PIN_MISMATCH));
        c->state = INKY_TLS_OPEN;
    }
    RETURN(progress(c, result));
}
int inky_tls_queue_plaintext(inky_tls_client *c, const uint8_t *data, size_t count) {
    LOCK();
    if (!c || !data || !count || count > MAX_PLAINTEXT) RETURN(INKY_TLS_INVALID_ARGUMENT);
    if (c->state != INKY_TLS_OPEN) RETURN(INKY_TLS_INVALID_STATE);
    if (c->pending_length) RETURN(INKY_TLS_BACKPRESSURE);
    memcpy(c->pending, data, count); c->pending_length = count; c->pending_offset = 0;
    RETURN(INKY_TLS_OK);
}
int inky_tls_flush_plaintext(inky_tls_client *c) {
    LOCK();
    if (!c) RETURN(INKY_TLS_INVALID_ARGUMENT);
    if (c->state == INKY_TLS_FAILED) RETURN(c->error);
    if (c->state != INKY_TLS_OPEN) RETURN(INKY_TLS_INVALID_STATE);
    if (!c->pending_length) RETURN(INKY_TLS_OK);
    int result = mbedtls_ssl_write(&c->ssl, c->pending + c->pending_offset,
                                  c->pending_length - c->pending_offset);
    if (result > 0) {
        c->pending_offset += (size_t)result;
        if (c->pending_offset == c->pending_length) {
            mbedtls_platform_zeroize(c->pending, sizeof(c->pending));
            c->pending_length = c->pending_offset = 0;
            RETURN(INKY_TLS_OK);
        }
        RETURN(INKY_TLS_WANT_WRITE);
    }
    RETURN(progress(c, result));
}
int inky_tls_read_plaintext(inky_tls_client *c, uint8_t *data, size_t count) {
    LOCK();
    if (!c || !data || !count || count > MAX_PLAINTEXT) RETURN(INKY_TLS_INVALID_ARGUMENT);
    if (c->state == INKY_TLS_FAILED) RETURN(c->error);
    if (c->state == INKY_TLS_CLOSED_STATE) RETURN(-INKY_TLS_CLOSED);
    if (c->state != INKY_TLS_OPEN && c->state != INKY_TLS_CLOSING) RETURN(INKY_TLS_INVALID_STATE);
    int result = mbedtls_ssl_read(&c->ssl, data, count);
    if (result == MBEDTLS_ERR_SSL_WANT_READ) RETURN(-INKY_TLS_WANT_READ);
    if (result == MBEDTLS_ERR_SSL_WANT_WRITE) RETURN(-INKY_TLS_WANT_WRITE);
    if (result == MBEDTLS_ERR_SSL_PEER_CLOSE_NOTIFY) {
        c->peer_closed = 1;
        c->state = INKY_TLS_CLOSED_STATE;
        mbedtls_platform_zeroize(c->pending, sizeof(c->pending));
        c->pending_length = c->pending_offset = 0;
        RETURN(-INKY_TLS_CLOSED);
    }
    if (!result) RETURN(fail(c, INKY_TLS_TRUNCATED));
    RETURN(result < 0 ? fail(c, result) : result);
}
int inky_tls_close(inky_tls_client *c) {
    LOCK();
    if (!c) RETURN(INKY_TLS_INVALID_ARGUMENT);
    if (c->state == INKY_TLS_CLOSED_STATE && c->close_sent) RETURN(INKY_TLS_OK);
    if (c->state != INKY_TLS_OPEN && c->state != INKY_TLS_CLOSING &&
        !(c->state == INKY_TLS_CLOSED_STATE && c->peer_closed)) RETURN(INKY_TLS_INVALID_STATE);
    if (c->pending_length) RETURN(INKY_TLS_BACKPRESSURE);
    if (!c->peer_closed) c->state = INKY_TLS_CLOSING;
    int result = mbedtls_ssl_close_notify(&c->ssl);
    if (!result) c->close_sent = 1;
    RETURN(progress(c, result));
}
void inky_tls_transport_ended(inky_tls_client *c) { LOCK(); if (c) c->transport_ended = 1; pthread_mutex_unlock(&library_lock); }
int inky_tls_state(inky_tls_client *c) { LOCK(); RETURN(c ? c->state : INKY_TLS_FAILED); }
size_t inky_tls_pending_plaintext(inky_tls_client *c) {
    LOCK(); size_t count = c ? c->pending_length - c->pending_offset : 0;
    pthread_mutex_unlock(&library_lock); return count;
}
size_t inky_tls_receive_capacity(inky_tls_client *c) {
    LOCK(); size_t count = c ? c->input.capacity - c->input.count : 0;
    pthread_mutex_unlock(&library_lock); return count;
}
void inky_tls_error_description(int code, char *buffer, size_t size) {
    LOCK(); mbedtls_strerror(code, buffer, size); pthread_mutex_unlock(&library_lock);
}
