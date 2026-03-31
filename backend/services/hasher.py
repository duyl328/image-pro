"""Hash computation service — xxHash, SHA-256, and dHash."""

import hashlib
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from pathlib import Path

import xxhash

from config import QUICK_HASH_CHUNK_SIZE


def compute_xxhash_partial(file_path: str) -> str:
    """Compute xxHash of first 8KB + last 8KB for quick comparison."""
    h = xxhash.xxh64()
    size = Path(file_path).stat().st_size
    chunk = QUICK_HASH_CHUNK_SIZE

    with open(file_path, "rb") as f:
        h.update(f.read(chunk))
        if size > chunk * 2:
            f.seek(-chunk, 2)
            h.update(f.read(chunk))

    return h.hexdigest()


def compute_sha256(file_path: str) -> str:
    """Compute full SHA-256 hash."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            data = f.read(65536)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def compute_dhash(file_path: str, hash_size: int = 8) -> str:
    """Compute dHash (difference hash) for perceptual similarity.

    Returns hex string of 64-bit hash.
    Must run in separate process because Pillow doesn't release GIL during decode.
    """
    from PIL import Image

    try:
        img = Image.open(file_path).convert("L")
        img = img.resize((hash_size + 1, hash_size), Image.LANCZOS)
        pixels = list(img.getdata())

        bits = []
        for row in range(hash_size):
            for col in range(hash_size):
                idx = row * (hash_size + 1) + col
                bits.append(1 if pixels[idx] > pixels[idx + 1] else 0)

        # Convert bits to hex
        hash_int = 0
        for bit in bits:
            hash_int = (hash_int << 1) | bit
        return f"{hash_int:016x}"
    except Exception:
        return None


def hamming_distance(hash1: str, hash2: str) -> int:
    """Compute hamming distance between two hex hash strings."""
    val = int(hash1, 16) ^ int(hash2, 16)
    return bin(val).count("1")
