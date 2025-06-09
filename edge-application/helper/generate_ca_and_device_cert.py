#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: generate_ca_and_device_cert.py
# Author: Rajaram Lakshmanan
# Description:  Helper to generate a root CA and signed device certificate(s)
# for Azure IoT Hub.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import os
import logging
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CertificateGenerator")


def create_key():
    """Generate a 2048-bit RSA private key"""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def save_pem_file(data, path, mode=0o600):
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, mode)
    logger.info(f"Saved: {path}")


def generate_root_ca(cert_dir):
    logger.info("Generating Root CA...")
    ca_key = create_key()
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "NO"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Viken"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Drammen"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Student"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Not Applicable"),
        x509.NameAttribute(NameOID.COMMON_NAME, "digital_twin_rpms"),
        x509.NameAttribute(NameOID.EMAIL_ADDRESS, "rajaraml@ntnu.no"),
    ])

    now = datetime.now(timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    # Save CA key and cert
    save_pem_file(ca_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ), os.path.join(cert_dir, "rootCA.key"))

    save_pem_file(ca_cert.public_bytes(serialization.Encoding.PEM),
                  os.path.join(cert_dir, "rootCA.pem"))

    return ca_key, ca_cert


def load_root_ca(cert_path, key_path):
    """Load the existing Root CA certificate and key."""
    with open(cert_path, "rb") as cert_file:
        ca_cert = x509.load_pem_x509_certificate(cert_file.read())

    with open(key_path, "rb") as key_file:
        ca_key = serialization.load_pem_private_key(key_file.read(), password=None)

    return ca_key, ca_cert


def generate_device_cert(device_id, ca_key, ca_cert, cert_dir):
    logger.info(f"Generating certificate for device: {device_id}")
    device_key = create_key()

    csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "NO"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Viken"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Drammen"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Student"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Not Applicable"),
        x509.NameAttribute(NameOID.COMMON_NAME, device_id),
        x509.NameAttribute(NameOID.EMAIL_ADDRESS, "rajaraml@ntnu.no"),
    ])).sign(device_key, hashes.SHA256())

    now = datetime.now(timezone.utc)
    device_cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(ca_cert.subject)
        .public_key(device_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    # Calculate the SHA-256 thumbprint twice (for both primary and secondary)
    sha256_thumbprint = device_cert.fingerprint(hashes.SHA256())

    # Convert to hex string and ensure uppercase
    sha256_thumbprint_hex = sha256_thumbprint.hex().upper()

    # Remove any unnecessary characters (if any)
    sha256_thumbprint_clean = sha256_thumbprint_hex.replace(":", "")

    # Validate the thumbprint length for Azure compatibility (should be 64 characters)
    logger.info(f"Raw SHA-256 Thumbprint (64 characters expected): {sha256_thumbprint_clean}")

    if len(sha256_thumbprint_clean) != 64:
        logger.error(f"Invalid SHA-256 thumbprint length: {len(sha256_thumbprint_clean)}")

    # Save device key and cert
    save_pem_file(device_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ), os.path.join(cert_dir, f"{device_id}.key"))

    save_pem_file(device_cert.public_bytes(serialization.Encoding.PEM),
                  os.path.join(cert_dir, f"{device_id}.pem"))

    return sha256_thumbprint_clean, sha256_thumbprint_clean  # Same thumbprint for both


def main():
    import argparse

    import sys

    sys.argv = ['generate_ca_and_device_cert.py',
                '--device-id', 'ble_c1_accelerometer,'
                               'ble_c1_ecg,'
                               'ble_c1_heart_rate,'
                               'ble_c1_ppg,'
                               'ble_c1_spo2,'
                               'ble_c1_temperature,'
                               'i2c_c1_environment,'
                               'i2c_c1_oximeter,'
                               'i2c_c2_ecg,'
                               'temperature_sensor,'
                               'edge_gateway',
                '--cert-dir',  'certificates',
                '--ca-cert', '/home/pi/rpms/helper/certificates/rootCA.pem',
                '--ca-key', '/home/pi/rpms/helper/certificates/rootCA.key']

    parser = argparse.ArgumentParser(description="Generate Root CA and signed device(s) certificate")
    parser.add_argument("--device-id",
                        required=True,
                        help="Comma-separated list of Device IDs (e.g., device1,device2,device3)")
    parser.add_argument("--cert-dir", default="certificates", help="Directory to save certificates")
    parser.add_argument("--ca-cert", help="Path to an existing Root CA certificate (optional)")
    parser.add_argument("--ca-key", help="Path to an existing Root CA key (optional)")
    args = parser.parse_args()

    # Get the list of device IDs
    device_ids = [d.strip() for d in args.device_id.split(',') if d.strip()]

    os.makedirs(args.cert_dir, exist_ok=True)

    # Step 1: Load or generate root CA
    if args.ca_cert and args.ca_key:
        ca_key, ca_cert = load_root_ca(args.ca_cert, args.ca_key)
        logger.info(f"Loaded existing Root CA from {args.ca_cert} and {args.ca_key}")
    else:
        ca_key, ca_cert = generate_root_ca(args.cert_dir)
        logger.info("Generated new Root CA.")

    # Step 2: Generate device cert signed by the CA
    for device_id in device_ids:
        generate_device_cert(device_id, ca_key, ca_cert, args.cert_dir)

    logger.info("All certificates successfully generated.")
    logger.info(f"Next: Upload 'rootCA.pem' to Azure IoT Hub as CA cert")
    logger.info(f"Use device cert '{args.device_id}.pem' and key '{args.device_id}.key' on device")


if __name__ == "__main__":
    main()