"""Download OpenCV Zoo YuNet and SFace ONNX models into models/."""
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models"
MODELS = {
    "face_detection_yunet_2023mar.onnx": "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx": "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}

def download(url, destination):
    request = Request(url, headers={"User-Agent": "AdvancedAttendanceProject/1.0"})
    with urlopen(request, timeout=60) as response, destination.open("wb") as output:
        output.write(response.read())

if __name__ == "__main__":
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in MODELS.items():
        path = MODEL_DIR / filename
        if path.exists() and path.stat().st_size > 100_000:
            print(f"Already present: {path}")
            continue
        print(f"Downloading {filename} ...")
        download(url, path)
        if path.stat().st_size < 100_000:
            path.unlink(missing_ok=True)
            raise RuntimeError(f"Download for {filename} appears incomplete; check the model URL.")
        print(f"Saved {path} ({path.stat().st_size:,} bytes)")
    print("Models ready. Verify licenses and terms for your intended use before deployment.")
