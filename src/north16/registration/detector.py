"""Optional local YOLO proposals; no downloads, no automatic box correspondence."""
from pathlib import Path
import hashlib


def detect(image, weight, confidence=.25, size=1280):
    path = Path(weight).resolve(strict=True)
    if path.suffix.lower() != ".pt":
        raise ValueError("首版使用本地Ultralytics .pt检测模型")
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise ValueError("检测为可选功能，请安装north16[detection]；配准与手工船框不依赖检测器") from exc
    model = YOLO(str(path), task="detect")
    allowed = [int(k) for k, name in model.names.items()
               if any(word in str(name).lower() for word in ("boat", "ship", "cargo", "vessel", "tug"))]
    if not allowed:
        raise ValueError(f"此模型没有可识别的船舶类别：{model.names}，请换权重或手工画框")
    result = model.predict(image[..., ::-1].copy(), classes=allowed, conf=float(confidence),
                           imgsz=int(size), device="cpu", verbose=False, save=False)[0]
    boxes = [dict(xyxy=row[:4].tolist(), confidence=float(row[4]), label=str(model.names[int(row[5])]),
                  source="detector_candidate", review_status="unreviewed") for row in result.boxes.data.cpu().numpy()]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return boxes, dict(path=str(path), sha256=digest, confidence=float(confidence), size=int(size),
                       classes={str(k): model.names[k] for k in allowed}, device="cpu")
