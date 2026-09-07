"""Create and sign ephemeral local fixtures for portable-update smoke tests."""
from __future__ import annotations
import argparse
import base64
import datetime as dt
import hashlib
import ipaddress
import json
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.x509.oid import NameOID

def init(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    signing = ed25519.Ed25519PrivateKey.generate()
    private_bytes = signing.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    (root / "manifest-private.pem").write_bytes(private_bytes)
    public = signing.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    tls_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(tls_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1))
        .not_valid_after(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.DNSName("localhost")]
            ),
            critical=False,
        )
        .sign(tls_key, hashes.SHA256())
    )
    (root / "tls-key.pem").write_bytes(
        tls_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    pem = certificate.public_bytes(serialization.Encoding.PEM)
    (root / "tls-cert.pem").write_bytes(pem)
    print(json.dumps({"public_key_b64": base64.b64encode(public).decode(), "ca_pem_b64": base64.b64encode(pem).decode()}))

def manifest(root: Path, asset: Path, port: int) -> None:
    digest = hashlib.sha256()
    with asset.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    sha = digest.hexdigest()
    payload = f"1|0.2.2|{asset.name}|{asset.stat().st_size}|{sha}".encode()
    key = serialization.load_pem_private_key((root / "manifest-private.pem").read_bytes(), password=None)
    signature = base64.b64encode(key.sign(payload)).decode()
    item = {
        "schema": 1,
        "version": "0.2.2",
        "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "notes_url": "https://example.invalid/update-test",
        "asset": {
            "name": asset.name,
            "url": f"https://127.0.0.1:{port}/{asset.name}",
            "size": asset.stat().st_size,
            "sha256": sha,
        },
        "minimum_windows": "10.0.17134",
        "signature": signature,
    }
    (root / "server" / "latest-portable.json").write_text(json.dumps(item), encoding="utf-8")
    (root / "manifest-private.pem").unlink()

parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers(dest="action", required=True)
for name in ("init", "manifest"):
    command = subparsers.add_parser(name)
    command.add_argument("--root", required=True)
subparsers.choices["manifest"].add_argument("--asset", required=True)
subparsers.choices["manifest"].add_argument("--port", type=int, required=True)

arguments = parser.parse_args()
if arguments.action == "init":
    init(Path(arguments.root))
else:
    manifest(Path(arguments.root), Path(arguments.asset), arguments.port)
