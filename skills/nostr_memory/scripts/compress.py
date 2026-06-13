#!/usr/bin/env python3
# Copyright 2026 Bob Ros
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Compression utilities for Nostr memory serialization."""

import gzip
import io
import os
import tarfile
from typing import Tuple

COMPRESSION_NONE = 'none'
COMPRESSION_GZ = 'gz'
COMPRESSION_TAR_GZ = 'tar.gz'


def compress_data(data: bytes, fmt: str) -> Tuple[bytes, str]:
    """
    Compress binary data.

    Returns (compressed_bytes, actual_compression_format)
    """
    if fmt == COMPRESSION_GZ:
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=6) as f:
            f.write(data)
        return buf.getvalue(), COMPRESSION_GZ

    if fmt == COMPRESSION_TAR_GZ:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz', compresslevel=6) as tar:
            info = tarfile.TarInfo(name='data')
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        return buf.getvalue(), COMPRESSION_TAR_GZ

    return data, COMPRESSION_NONE


def decompress_data(data: bytes, fmt: str) -> bytes:
    """Decompress binary data."""
    if fmt == COMPRESSION_GZ:
        return gzip.decompress(data)

    if fmt == COMPRESSION_TAR_GZ:
        buf = io.BytesIO(data)
        with tarfile.open(fileobj=buf, mode='r:gz') as tar:
            member = tar.next()
            if member is None:
                raise ValueError('Empty tar.gz archive')
            return tar.extractfile(member).read()

    return data


def compress_directory(dir_path: str) -> Tuple[bytes, str]:
    """
    Compress an entire directory as tar.gz.

    Returns (compressed_bytes, COMPRESSION_TAR_GZ)
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz', compresslevel=6) as tar:
        tar.add(dir_path, arcname=os.path.basename(dir_path))
    return buf.getvalue(), COMPRESSION_TAR_GZ
