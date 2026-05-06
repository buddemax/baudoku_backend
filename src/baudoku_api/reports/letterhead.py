from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile


BBA_BLUE = "017FC1"
BBA_TEXT = "1F1A3D"

CONTACT_COLUMNS = [
    ("Geschäftssitz", ["Dr. Ing. Jörn Budde", "Silberberger Chaussee 14", "15526 Bad Saarow"]),
    ("Internet", ["www.baugutachten-budde.de", "www.abdichtung-budde.de"]),
    ("E-Mail", ["info@bba-badsaarow.de", "buchhaltung@bba-badsaarow.de"]),
    ("Telefon", ["+49 33631 5663", "+49 33631 58374", "+49 171 2065 769"]),
]


def logo_bytes_from_template(template_path: Path) -> bytes | None:
    try:
        with ZipFile(template_path) as archive:
            media_names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("word/media/") and name.lower().endswith(".png")
            )
            if not media_names:
                return None
            return archive.read(media_names[0])
    except Exception:
        return None
