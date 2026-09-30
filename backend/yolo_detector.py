from pathlib import Path
from threading import Lock

from ultralytics import YOLO


class DentalDetector:
    def __init__(self, model_path: Path):
        self.model_path = model_path
        self._model = None
        self._lock = Lock()

    def _get_model(self) -> YOLO:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    if not self.model_path.exists():
                        raise FileNotFoundError(f"Model weights not found: {self.model_path}")
                    self._model = YOLO(str(self.model_path))
        return self._model

    def predict(self, image_rgb, confidence: float = 0.25) -> tuple[list[dict], object]:
        model = self._get_model()
        result = model.predict(source=image_rgb, conf=confidence, verbose=False)[0]
        detections = []
        for box in result.boxes:
            class_id = int(box.cls[0])
            detections.append({
                "class": str(result.names[class_id]),
                "confidence": round(float(box.conf[0]) * 100, 2),
                "bbox": [round(float(value), 2) for value in box.xyxy[0].tolist()],
            })
        detections.sort(key=lambda item: item["confidence"], reverse=True)
        return detections, result
