import secrets
import zipfile
from base64 import b64decode, b64encode
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def encrypt(key: str, plaintext: str, associated_data: str):
    iv = secrets.token_hex()

    encryptor = Cipher(
        algorithms.AES(key.encode()),
        modes.GCM(iv.encode()),
    ).encryptor()

    encryptor.authenticate_additional_data(associated_data.encode())
    data = b64encode(plaintext.encode())
    ciphertext = encryptor.update(data) + encryptor.finalize()

    return iv, b64encode(ciphertext).decode(), b64encode(encryptor.tag).decode()


def decrypt(key: str, associated_data: str, iv: str, ciphertext: str, tag: str):
    decryptor = Cipher(
        algorithms.AES(key.encode()),
        modes.GCM(iv.encode(), b64decode(tag)),
    ).decryptor()

    decryptor.authenticate_additional_data(associated_data.encode())
    return b64decode(decryptor.update(b64decode(ciphertext)) + decryptor.finalize()).decode()


def extract_files(zip_path: Path, extract_path: Path):
    with zipfile.ZipFile(zip_path) as zf:
        for zip_file in zf.namelist():
            if zip_file.endswith('/'):
                continue
            try:
                file_name = zip_file.encode('cp437').decode('gbk')
            except Exception as e:
                file_name = zip_file.encode('cp437').decode('utf-8')
            (extract_path / file_name).parent.mkdir(exist_ok=True, parents=True)
            with open(extract_path / file_name, 'wb') as f:
                f.write(zf.read(zip_file))
