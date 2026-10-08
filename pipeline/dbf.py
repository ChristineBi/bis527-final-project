"""Read DATASUS .dbc files.

A .dbc file is a compressed .dbf (dBase) table. We decompress it with
pyreaddbc, then read the fixed-width .dbf records with numpy, which is much
faster than parsing records one at a time. Every value is read as text, so
nothing is lost to automatic type guessing; dates and numbers are parsed
later in SQL.
"""
import struct
import tempfile
from pathlib import Path

import numpy as np
import pyreaddbc

ENCODING = "latin-1"  # DATASUS files use Latin-1


def dbc_to_dbf(dbc_path, dbf_path):
    pyreaddbc.dbc2dbf(str(dbc_path), str(dbf_path))


def read_dbf(dbf_path, columns=None):
    """Return {column name: numpy array of str} for a .dbf file.

    columns: list of column names to keep (default: all). Deleted records
    are dropped. Empty values become "".
    """
    raw = Path(dbf_path).read_bytes()
    n_records, header_len, record_len = struct.unpack("<IHH", raw[4:12])

    fields = []  # (name, start, length)
    start = 1  # byte 0 of each record is the deletion flag
    pos = 32
    while raw[pos] != 0x0D:
        name = raw[pos:pos + 11].split(b"\x00")[0].decode("ascii").strip()
        length = raw[pos + 16]
        fields.append((name, start, length))
        start += length
        pos += 32
    if start != record_len:
        raise ValueError(f"{dbf_path}: field lengths add to {start}, "
                         f"but record length is {record_len}")

    body = raw[header_len:header_len + n_records * record_len]
    n_complete = len(body) // record_len
    records = np.frombuffer(body[:n_complete * record_len], dtype=np.uint8)
    records = records.reshape(n_complete, record_len)
    keep = records[:, 0] != ord("*")
    records = records[keep]

    wanted = set(columns) if columns else None
    out = {}
    for name, start, length in fields:
        if wanted is not None and name not in wanted:
            continue
        block = np.ascontiguousarray(records[:, start:start + length])
        values = block.view(f"S{length}").ravel()
        text = np.char.decode(values, ENCODING)
        out[name] = np.char.strip(np.char.strip(text), "\x00")
    if wanted is not None:
        missing = wanted - set(out)
        if missing:
            raise KeyError(f"{dbf_path}: missing columns {sorted(missing)}")
    return out


def read_dbc(dbc_path, columns=None):
    """Decompress a .dbc into a temporary .dbf and read it."""
    with tempfile.TemporaryDirectory() as tmp:
        dbf_path = Path(tmp) / (Path(dbc_path).stem + ".dbf")
        dbc_to_dbf(dbc_path, dbf_path)
        return read_dbf(dbf_path, columns)
