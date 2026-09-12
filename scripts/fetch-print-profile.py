"""Fetch ECI's original profile; its license restricts standalone redistribution."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile


URL = "https://eci.org/lib/exe/pso-coated_v3.zip"
PROFILE_SHA256 = "c30ad2c01e8f93135ec7682c535e0a81bc2d177c301e196376c5f5838b5c8e86"
ARCHIVE_SHA256 = "5c8ed32d40949c2e8b84a03642ca7aadc4e3f153237cf439d3cdddffffd4ed95"


def main():
    directory = Path(__file__).resolve().parents[1] / "assets" / "profiles"
    target = directory / "PSOcoated_v3.icc"
    if target.exists() and sha256(target.read_bytes()).hexdigest() == PROFILE_SHA256:
        print(f"Print profile already installed: {target}")
        return
    with urlopen(URL, timeout=60) as response:
        data = response.read()
    if sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("ECI archive checksum differs; inspect the download before updating the checksum")
    with ZipFile(BytesIO(data)) as archive:
        profile = archive.read(target.name)
        if sha256(profile).hexdigest() != PROFILE_SHA256:
            raise ValueError("Unexpected ICC profile checksum")
        directory.mkdir(parents=True, exist_ok=True)
        target.write_bytes(profile)
        (directory / "PSOcoated_v3_info.pdf").write_bytes(archive.read("PSOcoated_v3_info.pdf"))
    print(f"Installed print profile: {target}")


if __name__ == "__main__":
    main()
