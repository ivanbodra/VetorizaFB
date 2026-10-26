"""Lazy PaddleOCR 3.x adapter; no model initialization at import time."""


class PaddleRecognizer:
    def __init__(self, model_name="PP-OCRv6_small_rec", model_dir=None, device="cpu"):
        # Prefer complete local assets before importing the OCR stack.
        if model_dir is None:
            from .models import discover_models,default_model_root
            candidates=discover_models(default_model_root())
            model_dir=next((str(m.path) for m in candidates if m.name==model_name),None)
        from paddleocr import TextRecognition
        self.model_name, self.model_dir, self.device = model_name, model_dir, device
        self.model = TextRecognition(model_name=model_name, model_dir=model_dir, device=device)

    def predict(self, crops):
        if not crops:
            return []
        # The chart is RGB. Paddle's ndarray interface expects BGR.
        result = list(self.model.predict([c[:, :, ::-1].copy() for c in crops],
                                         batch_size=len(crops)))
        readings = [(str(r['rec_text']), float(r['rec_score'])) for r in result]
        if len(readings) != len(crops):
            raise RuntimeError("PaddleOCR returned an unexpected number of results")
        return readings
