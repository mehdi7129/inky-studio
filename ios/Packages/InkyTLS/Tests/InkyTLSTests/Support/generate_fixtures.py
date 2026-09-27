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


def main():
    os.umask(0o077)
    support = Path(__file__).resolve().parent
    package = support.parents[2]
    output = package / ".generated/test-fixtures"
    output.mkdir(parents=True, exist_ok=True)
    name = "frame-00000000-0000-4000-8000-000000000001.inky.invalid"
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    server, other = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    for label, key in [("server", server), ("other", other)]:
        (output / (label + ".key")).write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    start = datetime.now(UTC) - timedelta(minutes=5)
    end = start + timedelta(days=396)
    scenarios = [
        ("valid", server, start, end),
        ("other", other, start, end),
        ("expired", server, datetime(2000, 1, 1, tzinfo=UTC), datetime(2001, 1, 1, tzinfo=UTC)),
        ("future", server, datetime(2098, 1, 1, tzinfo=UTC), datetime(2099, 1, 1, tzinfo=UTC)),
    ]
    for label, key, begins, ends in scenarios:
        certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(begins).not_valid_after(ends)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False, key_agreement=False,
                key_cert_sign=True, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .sign(key, hashes.SHA256()))
        for extension, encoding in [("pem", serialization.Encoding.PEM), ("der", serialization.Encoding.DER)]:
            (output / f"{label}.{extension}").write_bytes(certificate.public_bytes(encoding))
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
