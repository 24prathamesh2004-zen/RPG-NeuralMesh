"""Local sentence embedder: all-MiniLM-L6-v2 through ONNX Runtime, so no text leaves the process.

The model folder holds model.onnx and tokenizer.json. It is read from NEURALMESH_EMBEDDING_MODEL_DIR,
or from the ONNX copy that Chroma caches (the same model SkillForge uses by default).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

DIMENSIONS = 384
_DEFAULT_DIRS = (
    Path.home() / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2" / "onnx",
    Path(__file__).resolve().parents[1] / ".neuralmesh" / "models" / "all-MiniLM-L6-v2",
)
_lock = threading.Lock()
_model = None


class EmbeddingModelMissing(RuntimeError):
    pass


def model_dir() -> Path | None:
    configured = os.getenv("NEURALMESH_EMBEDDING_MODEL_DIR")
    candidates = [Path(configured)] if configured else list(_DEFAULT_DIRS)
    for path in candidates:
        if (path / "model.onnx").is_file() and (path / "tokenizer.json").is_file():
            return path
    return None


def available() -> bool:
    return model_dir() is not None


class _MiniLM:
    def __init__(self, path: Path) -> None:
        import onnxruntime
        from tokenizers import Tokenizer

        self.tokenizer = Tokenizer.from_file(str(path / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=256)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = onnxruntime.InferenceSession(str(path / "model.onnx"), options, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}

    def embed(self, texts: list[str]) -> np.ndarray:
        out = []
        for start in range(0, len(texts), 32):
            batch = self.tokenizer.encode_batch(texts[start:start + 32])
            ids = np.array([e.ids for e in batch], dtype=np.int64)
            mask = np.array([e.attention_mask for e in batch], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feed)[0]
            summed = (hidden * mask[..., None]).sum(axis=1)
            pooled = summed / np.clip(mask.sum(axis=1, keepdims=True), 1, None)
            out.append(pooled)
        vectors = np.vstack(out).astype("float32") if out else np.zeros((0, DIMENSIONS), dtype="float32")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.clip(norms, 1e-12, None)


def embed(texts: list[str]) -> np.ndarray:
    """Return normalised vectors, shape (len(texts), 384). Inner product of two vectors is their cosine."""
    global _model
    if not texts:
        return np.zeros((0, DIMENSIONS), dtype="float32")
    with _lock:
        if _model is None:
            path = model_dir()
            if path is None:
                raise EmbeddingModelMissing(
                    "The all-MiniLM-L6-v2 ONNX model was not found. Set NEURALMESH_EMBEDDING_MODEL_DIR "
                    "to a folder with model.onnx and tokenizer.json."
                )
            _model = _MiniLM(path)
        return _model.embed(texts)
