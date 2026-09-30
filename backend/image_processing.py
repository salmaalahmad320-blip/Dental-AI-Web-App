from io import BytesIO

import cv2
import numpy as np
from PIL import Image


def decode_image(image_bytes: bytes) -> np.ndarray:
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    rgb_image = np.asarray(image)
    return cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR)


def apply_medical_enhancement(image_bgr: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    enhanced_l = clahe.apply(l_channel)
    enhanced_lab = cv2.merge((enhanced_l, a_channel, b_channel))
    enhanced_bgr = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
    filtered_bgr = cv2.bilateralFilter(enhanced_bgr, 9, 75, 75)
    return cv2.cvtColor(filtered_bgr, cv2.COLOR_BGR2RGB)


def encode_jpeg(image_rgb: np.ndarray) -> bytes:
    success, encoded = cv2.imencode(".jpg", cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR))
    if not success:
        raise ValueError("Unable to encode the processed image")
    return encoded.tobytes()


def annotate_detections(image_rgb: np.ndarray, detections: list[dict]) -> np.ndarray:
    annotated = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR).copy()
    colors = {
        "Fillings": (0, 215, 255),
        "Implant": (255, 100, 0),
        "Cavity": (55, 70, 255),
        "Impacted Tooth": (80, 220, 80),
    }
    height, width = annotated.shape[:2]
    thickness = max(2, round(min(width, height) / 240))
    font_scale = max(0.45, min(width, height) / 900)

    for detection in detections:
        x1, y1, x2, y2 = [round(value) for value in detection["bbox"]]
        x1 = max(0, min(x1, width - 1))
        y1 = max(0, min(y1, height - 1))
        x2 = max(x1 + 1, min(x2, width - 1))
        y2 = max(y1 + 1, min(y2, height - 1))
        name = f'{detection["class"]} {detection["confidence"]:.0f}%'
        color = colors.get(detection["class"], (255, 255, 0))
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness, cv2.LINE_AA)
        (text_width, text_height), baseline = cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        label_y = y1 - 8
        if label_y - text_height - baseline < 0:
            label_y = y2 + text_height + baseline + 8
        label_y = min(label_y, height - 2)
        label_top = label_y - text_height - baseline - 5
        label_left = max(0, min(x1, width - text_width - 10))
        cv2.rectangle(annotated, (label_left, label_top), (label_left + text_width + 10, label_y), color, -1)
        cv2.putText(
            annotated,
            name,
            (label_left + 5, label_y - baseline - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (20, 20, 20),
            thickness,
            cv2.LINE_AA,
        )

    return cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
 