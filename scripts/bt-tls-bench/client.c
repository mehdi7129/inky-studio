#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "mbedtls/ssl.h"
#include "mbedtls/x509_crt.h"
#include "mbedtls/pk.h"
#include "mbedtls/error.h"
#include "psa/crypto.h"

/* Synthetic bench only: bounded memory BIOs, no sockets, BLE or credentials. */
#define CAP 65536
#define API __attribute__((visibility("default")))
typedef struct {
    mbedtls_ssl_context ssl;
    mbedtls_ssl_config conf;
    mbedtls_x509_crt ca;
    unsigned char rx[CAP], tx[CAP], pin[32];
    size_t rxlen, txlen, app_written;
    int authenticated, pin_seen, pin_rejected, last_error;
} client;

static int send_cb(void *opaque, const unsigned char *data, size_t len) {
    client *c = opaque;
    size_t n = len > 20 ? 20 : len;
    if (CAP - c->txlen < n) return MBEDTLS_ERR_SSL_WANT_WRITE;
    memcpy(c->tx + c->txlen, data, n); c->txlen += n;
    return (int)n;
}
static int recv_cb(void *opaque, unsigned char *data, size_t len) {
    client *c = opaque;
    if (!c->rxlen) return MBEDTLS_ERR_SSL_WANT_READ;
    size_t n = len < c->rxlen ? len : c->rxlen;
    if (n > 20) n = 20;
    memcpy(data, c->rx, n); c->rxlen -= n;
    memmove(c->rx, c->rx + n, c->rxlen);
    return (int)n;
}
static int verify_cb(void *opaque, mbedtls_x509_crt *cert, int depth, uint32_t *flags) {
    client *c = opaque;
    if (depth != 0) return 0;
    unsigned char der[2048], digest[32]; size_t digest_len = 0;
    int len = mbedtls_pk_write_pubkey_der(&cert->pk, der, sizeof(der));
    int ok = len > 0 && psa_hash_compute(PSA_ALG_SHA_256,
        der + sizeof(der) - len, (size_t)len, digest, sizeof(digest), &digest_len) == PSA_SUCCESS;
    if (!ok || digest_len != 32 || memcmp(c->pin, digest, 32) != 0) {
        c->pin_rejected = 1;
        *flags |= MBEDTLS_X509_BADCERT_OTHER;
    } else c->pin_seen = 1;
    /* Preserve all chain, date and hostname errors. Never clear flags. */
    return 0;
}
API void bench_free(client *c) {
    if (!c) return;
    mbedtls_ssl_free(&c->ssl); mbedtls_ssl_config_free(&c->conf);
    mbedtls_x509_crt_free(&c->ca); free(c);
}
API client *bench_new(const unsigned char *ca, size_t ca_len, const unsigned char *pin, int *error) {
    client *c = calloc(1, sizeof(*c));
    if (!c) { *error = -1; return NULL; }
    mbedtls_ssl_init(&c->ssl); mbedtls_ssl_config_init(&c->conf); mbedtls_x509_crt_init(&c->ca);
    memcpy(c->pin, pin, 32);
    int ret = (int)psa_crypto_init();
    if (!ret) ret = mbedtls_x509_crt_parse(&c->ca, ca, ca_len);
    if (!ret) ret = mbedtls_ssl_config_defaults(&c->conf, MBEDTLS_SSL_IS_CLIENT,
        MBEDTLS_SSL_TRANSPORT_STREAM, MBEDTLS_SSL_PRESET_DEFAULT);
    if (ret) goto fail;
    mbedtls_ssl_conf_min_tls_version(&c->conf, MBEDTLS_SSL_VERSION_TLS1_3);
    mbedtls_ssl_conf_max_tls_version(&c->conf, MBEDTLS_SSL_VERSION_TLS1_3);
    mbedtls_ssl_conf_authmode(&c->conf, MBEDTLS_SSL_VERIFY_REQUIRED);
    mbedtls_ssl_conf_ca_chain(&c->conf, &c->ca, NULL);
    mbedtls_ssl_conf_verify(&c->conf, verify_cb, c);
#if defined(MBEDTLS_SSL_SESSION_TICKETS)
    mbedtls_ssl_conf_session_tickets(&c->conf, MBEDTLS_SSL_SESSION_TICKETS_DISABLED);
#endif
#if defined(MBEDTLS_SSL_EARLY_DATA)
    mbedtls_ssl_conf_early_data(&c->conf, MBEDTLS_SSL_EARLY_DATA_DISABLED);
#endif
    ret = mbedtls_ssl_setup(&c->ssl, &c->conf);
    if (ret) goto fail;
    ret = mbedtls_ssl_set_hostname(&c->ssl, "inky-bench.test");
    if (ret) goto fail;
    mbedtls_ssl_set_bio(&c->ssl, c, send_cb, recv_cb, NULL);
    *error = 0; return c;
fail:
    *error = ret; bench_free(c); return NULL;
}
API int bench_handshake(client *c) {
    if (c->authenticated) return 0;
    if (c->last_error) return c->last_error;
    int ret = mbedtls_ssl_handshake(&c->ssl);
    if (ret == MBEDTLS_ERR_SSL_WANT_READ || ret == MBEDTLS_ERR_SSL_WANT_WRITE) return 1;
    if (!ret && c->pin_seen && !c->pin_rejected && !mbedtls_ssl_get_verify_result(&c->ssl)) {
        c->authenticated = 1; return 0;
    }
    c->last_error = ret ? ret : -2; return c->last_error;
}
API int bench_feed(client *c, const unsigned char *data, size_t len) {
    if (len > CAP - c->rxlen) return -1;
    memcpy(c->rx + c->rxlen, data, len); c->rxlen += len; return (int)len;
}
API int bench_take(client *c, unsigned char *data, size_t cap) {
    size_t n = cap < c->txlen ? cap : c->txlen;
    memcpy(data, c->tx, n); c->txlen -= n; memmove(c->tx, c->tx + n, c->txlen); return (int)n;
}
API int bench_write(client *c, const unsigned char *data, size_t len) {
    if (!c->authenticated || c->last_error) return -3;
    int ret = mbedtls_ssl_write(&c->ssl, data, len);
    if (ret > 0) c->app_written += (size_t)ret;
    return ret;
}
API int bench_read(client *c, unsigned char *data, size_t cap) {
    if (!c->authenticated || c->last_error) return -3;
    return mbedtls_ssl_read(&c->ssl, data, cap);
}
API int bench_close(client *c) { return mbedtls_ssl_close_notify(&c->ssl); }
API size_t bench_app_written(client *c) { return c->app_written; }
API int bench_pin_rejected(client *c) { return c->pin_rejected; }
API const char *bench_version(client *c) { return mbedtls_ssl_get_version(&c->ssl); }
API void bench_error(int code, char *buffer, size_t len) { mbedtls_strerror(code, buffer, len); }
