import io
import os
import sys

from PIL import Image

_pkg_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_pkg_dir)
_tessdata_default = os.path.join(_project_root, "tessdata")
TESSDATA = _tessdata_default if os.path.isdir(_tessdata_default) else os.environ.get("TESSDATA_PREFIX", "")


def debug(msg):
    print(f"[debug ocr] {msg}", file=sys.stderr)


def ocr_image(image_bytes: bytes) -> str:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        from tesserocr import PyTessBaseAPI

        with PyTessBaseAPI(path=TESSDATA) as api:
            api.SetImage(img)
            text = api.GetUTF8Text()
            return text.strip()
    except Exception as e:
        debug(f"OCR error: {e}")
        return ""
