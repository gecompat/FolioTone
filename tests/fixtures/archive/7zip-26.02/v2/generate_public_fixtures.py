from __future__ import annotations

import io
import sys
import tarfile
import zipfile
from pathlib import Path


def zip_directory(target: Path) -> None:
    info = zipfile.ZipInfo("directory/", (1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (0o40755 << 16) | 0x10
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(info, b"")


def zip_plaintext(target: Path) -> None:
    payload = b"FolioTone public plaintext fixture v2\n"
    info = zipfile.ZipInfo("plaintext.txt", (1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    with zipfile.ZipFile(target, "w", compresslevel=9) as archive:
        archive.writestr(info, payload)


def base_info(name: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def tar_directory(target: Path) -> None:
    info = base_info("directory/")
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    with tarfile.open(target, "w", format=tarfile.USTAR_FORMAT) as archive:
        archive.addfile(info)


def tar_symbolic_link(target: Path) -> None:
    info = base_info("link")
    info.type = tarfile.SYMTYPE
    info.linkname = "target"
    info.mode = 0o777
    with tarfile.open(target, "w", format=tarfile.USTAR_FORMAT) as archive:
        archive.addfile(info)


def tar_hard_link(target: Path) -> None:
    payload = b"FolioTone public hard-link target v2\n"
    regular = base_info("target")
    regular.type = tarfile.REGTYPE
    regular.mode = 0o644
    regular.size = len(payload)
    link = base_info("link")
    link.type = tarfile.LNKTYPE
    link.linkname = "target"
    link.mode = 0o644
    with tarfile.open(target, "w", format=tarfile.USTAR_FORMAT) as archive:
        archive.addfile(regular, io.BytesIO(payload))
        archive.addfile(link)


def main() -> None:
    root = Path(sys.argv[1])
    root.mkdir(parents=True, exist_ok=False)
    zip_plaintext(root / "zip-plaintext.zip")
    zip_directory(root / "zip-directory.zip")
    tar_directory(root / "tar-directory.tar")
    tar_symbolic_link(root / "tar-symbolic-link.tar")
    tar_hard_link(root / "tar-hard-link.tar")


if __name__ == "__main__":
    main()
