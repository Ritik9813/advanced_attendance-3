"""OpenCV Zoo YuNet + SFace face detector/recognizer.

Model files are downloaded by scripts/download_models.py. This module deliberately
fails closed when models are missing: no attendance is marked without a valid match.
"""
import base64
import re
from pathlib import Path
import cv2
import numpy as np

class FaceEngineError(Exception):
    pass

class FaceEngine:
    def __init__(self, model_dir: Path):
        detector_path = Path(model_dir) / "face_detection_yunet_2023mar.onnx"
        recognizer_path = Path(model_dir) / "face_recognition_sface_2021dec.onnx"
        if not detector_path.exists() or not recognizer_path.exists():
            raise FaceEngineError(
                "Face models are missing. Run: python scripts/download_models.py"
            )
        self.detector_path = str(detector_path)
        self.recognizer_path = str(recognizer_path)
        self.detector = cv2.FaceDetectorYN_create(
            self.detector_path, "", (320, 320), 0.85, 0.3, 5000
        )
        self.recognizer = cv2.FaceRecognizerSF_create(self.recognizer_path, "")

    @staticmethod
    def decode_image(image_bytes):
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            raise FaceEngineError("Image could not be decoded.")
        if image.shape[0] < 80 or image.shape[1] < 80:
            raise FaceEngineError("Image is too small. Use a clear image at least 80x80 pixels.")
        return image

    @staticmethod
    def decode_data_url(value):
        if not isinstance(value, str):
            raise FaceEngineError("Missing image data.")
        match = re.fullmatch(r"data:image/(jpeg|jpg|png);base64,([A-Za-z0-9+/=\r\n]+)", value)
        if not match:
            raise FaceEngineError("Image must be a base64 JPEG or PNG data URL.")
        try:
            raw = base64.b64decode(match.group(2), validate=True)
        except Exception as exc:
            raise FaceEngineError("Invalid image encoding.") from exc
        if len(raw) > 7 * 1024 * 1024:
            raise FaceEngineError("Image is too large.")
        return raw

    def embedding_from_bytes(self, image_bytes):
        image = self.decode_image(image_bytes)
        h, w = image.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(image)
        if faces is None or len(faces) == 0:
            raise FaceEngineError("No face detected. Improve lighting and face the camera.")
        if len(faces) > 1:
            raise FaceEngineError("More than one face detected. Use an image with one person.")
        face = faces[0]
        aligned = self.recognizer.alignCrop(image, face)
        feature = self.recognizer.feature(aligned).flatten().astype(np.float32)
        norm = float(np.linalg.norm(feature))
        if norm == 0:
            raise FaceEngineError("Could not create a valid face embedding.")
        feature = feature / norm
        return feature.tolist()

    def similarity(self, embedding_a, embedding_b):
        a = np.asarray(embedding_a, dtype=np.float32).reshape(1, -1)
        b = np.asarray(embedding_b, dtype=np.float32).reshape(1, -1)
        return float(self.recognizer.match(a, b, cv2.FaceRecognizerSF_FR_COSINE))
