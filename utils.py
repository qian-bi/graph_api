import logging
import secrets
import zipfile
from base64 import b64decode, b64encode
from pathlib import Path
from queue import Queue
from threading import Lock, Thread

import requests
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


class ThreadDownload:

    def __init__(self,
                 size: int,
                 url: str,
                 local_path: str,
                 headers: dict = None,
                 chunk: int = 1048576,
                 **kwargs) -> None:
        if size <= 0 or chunk <= 0:
            raise ValueError('invalid params')
        self.queue = Queue()
        for i in range(0, size, chunk):
            self.queue.put((i, i + chunk - 1))
        self.error_queue = Queue()
        self.local_path = local_path
        self.url = url
        self.headers = headers
        self.kwargs = kwargs
        self.lock = Lock()
        with open(local_path, 'wb') as f:
            f.seek(size - 1)
            f.write(b'\x00')

    def download(self):
        while True:
            with self.lock:
                if self.queue.empty():
                    return
                content_range = self.queue.get()
            headers = {'Range': f'bytes={content_range[0]}-{content_range[1]}'}
            if self.headers:
                headers.update(self.headers)
            self._download(content_range, headers)
            if not self.error_queue.empty():
                return

    def _download(self, content_range, headers):
        for i in range(0, 3):
            try:
                with requests.get(self.url, headers=headers, stream=True,
                                  **self.kwargs) as r, open(self.local_path, 'rb+') as f:
                    f.seek(content_range[0])
                    for content in r.iter_content(chunk_size=8912):
                        if not content:
                            break
                        f.write(content)
                    return
            except Exception as e:
                logging.error('download failed, retry: %d, err: %s', i + 1, e)
        self.error_queue.put('download failed')

    def run(self, n: int = 5):
        tasks = [Thread(target=self.download) for _ in range(n)]
        for t in tasks:
            t.start()
        for t in tasks:
            t.join()
        if not self.error_queue.empty():
            raise ValueError('download failed')
