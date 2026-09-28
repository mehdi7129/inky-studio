"""Generate private, synthetic TLS fixtures; requires cryptography>=44,<51.

No OpenSSL CLI or architecture-specific installation path is needed. Only the
valid certificate and its public pin are copied into the Simulator test bundle.
"""
import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def der_value(tag, contents):
    """Minimal DER writer for deliberately invalid, still self-signed fixtures."""
    size = len(contents)
    length = bytes([size]) if size < 128 else bytes([0x80 | ((size.bit_length() + 7) // 8)]) + size.to_bytes((size.bit_length() + 7) // 8)
    return bytes([tag]) + length + contents


def inverted_validity(certificate, key):
    before = der_value(0x17, certificate.not_valid_before_utc.strftime("%y%m%d%H%M%SZ").encode("ascii"))
    after = der_value(0x17, certificate.not_valid_after_utc.strftime("%y%m%d%H%M%SZ").encode("ascii"))
    validity = der_value(0x30, before + after)
    tbs = certificate.tbs_certificate_bytes
    assert tbs.count(validity) == 1
    tbs = tbs.replace(validity, der_value(0x30, after + before), 1)
    signature = key.sign(tbs, ec.ECDSA(hashes.SHA256()))
    algorithm = bytes.fromhex("300a06082a8648ce3d040302")
    return x509.load_der_x509_certificate(der_value(0x30, tbs + algorithm + der_value(0x03, b"\x00" + signature)))


def main():
    os.umask(0o077)
    support = Path(__file__).resolve().parent
    package = support.parents[2]
    output = package / ".generated/test-fixtures"
    output.mkdir(parents=True, exist_ok=True)
    name = "frame-00000000-0000-4000-8000-000000000001.inky.invalid"
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    server, other = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    p384 = ec.generate_private_key(ec.SECP384R1())
    for label, key in [("server", server), ("other", other), ("p384", p384)]:
        (output / (label + ".key")).write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    start = datetime.now(UTC) - timedelta(minutes=5)
    end = start + timedelta(days=396)
    scenarios = [
        ("valid", server, start, end),
        ("other", other, start, end),
        ("expired", server, datetime(2000, 1, 1, tzinfo=UTC), datetime(2001, 1, 1, tzinfo=UTC)),
        ("future", server, datetime(2098, 1, 1, tzinfo=UTC), datetime(2099, 1, 1, tzinfo=UTC)),
        *[(label, server, start, end) for label in [
            "wrong-name", "wrong-san", "missing-san", "wrong-eku", "missing-eku",
            "missing-ku", "wrong-ku", "not-ca", "not-self-issued", "bad-signature",
            "renewed", "unknown-critical", "inverted-validity",
        ]],
        ("equal-validity", server, start, start),
        ("p384", p384, start, end),
    ]
    for label, key, begins, ends in scenarios:
        alternate = "frame-00000000-0000-4000-8000-000000000002.inky.invalid"
        alternate_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, alternate)])
        cert_subject = alternate_subject if label == "wrong-name" else subject
        cert_issuer = alternate_subject if label == "not-self-issued" else cert_subject
        builder = (x509.CertificateBuilder().subject_name(cert_subject).issuer_name(cert_issuer)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(begins).not_valid_after(ends)
            .add_extension(x509.BasicConstraints(ca=label != "not-ca", path_length=None), critical=True))
        if label != "missing-ku":
            builder = builder.add_extension(x509.KeyUsage(digital_signature=label != "wrong-ku", content_commitment=False,
                key_encipherment=False, data_encipherment=False, key_agreement=False,
                key_cert_sign=label != "not-ca", crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        if label != "missing-eku":
            usage = ExtendedKeyUsageOID.CLIENT_AUTH if label == "wrong-eku" else ExtendedKeyUsageOID.SERVER_AUTH
            builder = builder.add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
        if label != "missing-san":
            hostname = alternate if label in {"wrong-name", "wrong-san"} else name
            builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        if label == "unknown-critical":
            builder = builder.add_extension(
                x509.UnrecognizedExtension(x509.ObjectIdentifier("1.3.6.1.4.1.55555.1"), b"\x05\x00"), critical=True,
            )
        certificate = builder.sign(other if label == "bad-signature" else key, hashes.SHA256())
        if label == "inverted-validity":
            certificate = inverted_validity(certificate, key)
        for extension, encoding in [("pem", serialization.Encoding.PEM), ("der", serialization.Encoding.DER)]:
            (output / f"{label}.{extension}").write_bytes(certificate.public_bytes(encoding))
        spki = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        (output / f"{label}.pin").write_bytes(hashlib.sha256(spki).digest())
    (output / "chain.pem").write_bytes((output / "valid.pem").read_bytes() + (output / "other.pem").read_bytes())
    spki = server.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    (output / "spki.der").write_bytes(spki)
    (output / "pin.bin").write_bytes(hashlib.sha256(spki).digest())
    generated = support / "Generated"
    generated.mkdir(exist_ok=True)
    for filename in ["valid.der", "pin.bin"]:
        (generated / filename).write_bytes((output / filename).read_bytes())
    print(f"Synthetic fixtures: {output}")


if __name__ == "__main__":
    main()
