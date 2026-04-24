import hashlib
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

CHUNK_SIZE_BYTES = 1024 * 1024
HEADER_SAMPLE_BYTES = 8192


class FileTooLargeError(Exception):
    def __init__(self, max_file_size_bytes: int) -> None:
        self.max_file_size_bytes = max_file_size_bytes
        super().__init__(f"File exceeds max size of {max_file_size_bytes} bytes")


@dataclass(frozen=True)
class StoredUpload:
    file_size_bytes: int
    sha256: str
    header_bytes: bytes


async def save_upload(file: UploadFile, destination: Path, max_file_size_bytes: int) -> StoredUpload:
    hasher = hashlib.sha256()
    total = 0
    header = bytearray()

    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with destination.open("wb") as out:
            while chunk := await file.read(CHUNK_SIZE_BYTES):
                total += len(chunk)
                if total > max_file_size_bytes:
                    raise FileTooLargeError(max_file_size_bytes)

                if len(header) < HEADER_SAMPLE_BYTES:
                    header.extend(chunk[: HEADER_SAMPLE_BYTES - len(header)])

                hasher.update(chunk)
                out.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return StoredUpload(
        file_size_bytes=total,
        sha256=hasher.hexdigest(),
        header_bytes=bytes(header),
    )
