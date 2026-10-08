"""Download SINAN and SINASC files from the DATASUS file server.

Safe to re-run: a file is skipped when a local copy with the same size
already exists, an interrupted download resumes where it stopped, and
dropped connections are retried. Every file is recorded in
data/raw/manifest.csv with its size, SHA-256 hash, and whether it came from
the final or the preliminary folder.
"""
import csv
import ftplib
import hashlib
import re
import time
from datetime import datetime, timezone

from .config import (FTP_HOST, RAW, SINAN_DIRS, SINAN_DISEASES,
                     SINAN_FILE_YEARS, SINASC_DIRS, STUDY_YEARS, UFS)

MANIFEST = RAW / "manifest.csv"
MANIFEST_FIELDS = ["dataset", "file", "remote_path", "status", "bytes",
                   "sha256", "downloaded_utc"]


class FTPSession:
    """One FTP connection that reconnects when it drops."""

    def __init__(self, host=FTP_HOST):
        self.host = host
        self.ftp = None

    def connect(self):
        self.close()
        self.ftp = ftplib.FTP(self.host, timeout=120)
        self.ftp.login()
        self.ftp.voidcmd("TYPE I")  # binary mode, needed for SIZE

    def get(self):
        if self.ftp is None:
            self.connect()
        return self.ftp

    def close(self):
        if self.ftp is not None:
            try:
                self.ftp.quit()
            except Exception:  # a half-open connection can fail in odd ways
                try:
                    self.ftp.close()
                except Exception:
                    pass
            self.ftp = None

    def retry(self, action, tries=5):
        for attempt in range(1, tries + 1):
            try:
                return action()
            except ftplib.all_errors as err:
                if attempt == tries:
                    raise
                wait = 10 * attempt
                print(f"    connection problem ({err}); retrying in {wait}s")
                time.sleep(wait)
                self.close()  # the next attempt reconnects inside the try

    def listdir(self, path):
        names = self.retry(lambda: self.get().nlst(path))
        return [name.rsplit("/", 1)[-1] for name in names]

    def size(self, path):
        def ask():
            ftp = self.get()
            ftp.voidcmd("TYPE I")  # listing a folder switches back to text
            return ftp.size(path)
        return self.retry(ask)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_files(session, dirs, pattern, wanted):
    """Map key -> (status, remote path) for files whose names match pattern.

    pattern is a regex whose groups make the key. Earlier dirs win, so a
    final file is used instead of a preliminary one for the same key.
    """
    found = {}
    for status, folder in dirs:
        try:
            names = session.listdir(folder)
        except ftplib.error_perm as err:
            print(f"  could not list {folder}: {err}")
            continue
        for name in names:
            match = re.match(pattern, name, re.IGNORECASE)
            if not match:
                continue
            key = tuple(g.upper() for g in match.groups())
            if key in wanted and key not in found:
                found[key] = (status, f"{folder}/{name}")
    return found


def sinan_targets(session):
    wanted = {(d, f"{y % 100:02d}")
              for d in SINAN_DISEASES for y in SINAN_FILE_YEARS}
    return find_files(session, SINAN_DIRS, r"^(SIF[GC])BR(\d{2})\.dbc$",
                      wanted), wanted


def sinasc_targets(session):
    wanted = {(uf, str(y)) for uf in UFS for y in STUDY_YEARS}
    return find_files(session, SINASC_DIRS, r"^DN([A-Z]{2})(\d{4})\.dbc$",
                      wanted), wanted


def download_file(session, remote, local):
    """Download one file. Returns 'cached' or 'downloaded'."""
    size = session.size(remote)
    if local.exists() and local.stat().st_size == size:
        return "cached"
    local.parent.mkdir(parents=True, exist_ok=True)
    part = local.with_name(local.name + ".part")

    def attempt():
        offset = part.stat().st_size if part.exists() else 0
        if offset > size:
            part.unlink()
            offset = 0
        if offset == size:
            return
        with open(part, "ab") as f:
            session.get().retrbinary(f"RETR {remote}", f.write,
                                     rest=offset or None)

    session.retry(attempt)
    got = part.stat().st_size
    if got != size:
        raise RuntimeError(f"{remote}: got {got} bytes, expected {size}")
    part.replace(local)
    return "downloaded"


def load_manifest():
    if not MANIFEST.exists():
        return {}
    with open(MANIFEST, newline="") as f:
        return {row["file"]: row for row in csv.DictReader(f)}


def save_manifest(rows):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for name in sorted(rows):
            writer.writerow(rows[name])


def run(datasets=("sinan", "sinasc")):
    session = FTPSession()
    manifest = load_manifest()
    problems = []
    print(f"connecting to {FTP_HOST} ...")
    try:
        session.retry(session.connect, tries=3)
    except ftplib.all_errors as err:
        message = (f"Could not connect to {FTP_HOST} ({err}). The DATASUS "
                   "file server may be down; try again later. If it keeps "
                   "failing, try another network (FTP can be blocked on "
                   "some Wi-Fi or VPNs).")
        print(message)
        return [message]
    try:
        for dataset in datasets:
            finder = sinan_targets if dataset == "sinan" else sinasc_targets
            found, wanted = finder(session)
            missing = sorted(wanted - set(found))
            print(f"{dataset}: {len(found)} files found on the server, "
                  f"{len(missing)} not found")
            for key in missing:
                problems.append(f"{dataset}: no file for {key}")
            for i, key in enumerate(sorted(found), 1):
                status, remote = found[key]
                name = remote.rsplit("/", 1)[-1]
                local = RAW / dataset / name
                print(f"  [{i}/{len(found)}] {name} ({status}) ...",
                      end=" ", flush=True)
                try:
                    result = download_file(session, remote, local)
                except Exception as err:  # keep going, report at the end
                    print("FAILED")
                    problems.append(f"{name}: {err}")
                    continue
                print(result)
                old = manifest.get(name)
                if result == "cached" and old and old.get("sha256"):
                    continue
                manifest[name] = {
                    "dataset": dataset, "file": name, "remote_path": remote,
                    "status": status, "bytes": local.stat().st_size,
                    "sha256": sha256(local),
                    "downloaded_utc": datetime.now(timezone.utc)
                    .strftime("%Y-%m-%d %H:%M"),
                }
                save_manifest(manifest)
    finally:
        session.close()
        save_manifest(manifest)
    return problems
