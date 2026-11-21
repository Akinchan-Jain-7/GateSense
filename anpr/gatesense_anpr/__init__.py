"""GateSense ANPR worker: camera frames in, gate events out.

source (camera / video / folder) -> detector (YOLOv8, ONNX) -> plate crop -> OCR
  -> normaliser (clean + vote across frames) -> client (POST /api/v1/gate-events)
"""
