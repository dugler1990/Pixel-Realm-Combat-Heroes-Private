"""Idempotent TRELLIS.2 source patches for this pipeline.

- Skip gated briaai/RMBG-2.0: concept stills already have alpha.
- Transformers 5 moved DINOv3 encoder layers under .model.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path("/workspace/vendor/TRELLIS.2")
REMBG_OLD = (
    "pipeline.rembg_model = getattr(rembg, args['rembg_model']['name'])"
    "(**args['rembg_model']['args'])"
)
REMBG_NEW = "pipeline.rembg_model = None  # skip gated RMBG; input already has alpha"
REMBG_TO_OLD = "        self.rembg_model.to(self.device)"
REMBG_TO_NEW = "        if self.rembg_model is not None:\n            self.rembg_model.to(self.device)"

DINO_OLD = '''    def extract_features(self, image: torch.Tensor) -> torch.Tensor:
        image = image.to(self.model.embeddings.patch_embeddings.weight.dtype)
        hidden_states = self.model.embeddings(image, bool_masked_pos=None)
        position_embeddings = self.model.rope_embeddings(image)

        for i, layer_module in enumerate(self.model.layer):
            hidden_states = layer_module(
                hidden_states,
                position_embeddings=position_embeddings,
            )

        return F.layer_norm(hidden_states, hidden_states.shape[-1:])
'''
DINO_NEW = '''    def extract_features(self, image: torch.Tensor) -> torch.Tensor:
        image = image.to(self.model.embeddings.patch_embeddings.weight.dtype)
        layer_root = self.model if hasattr(self.model, "layer") else getattr(self.model, "model", self.model)
        if hasattr(layer_root, "layer"):
            hidden_states = self.model.embeddings(image, bool_masked_pos=None)
            position_embeddings = self.model.rope_embeddings(image)
            for i, layer_module in enumerate(layer_root.layer):
                hidden_states = layer_module(
                    hidden_states,
                    position_embeddings=position_embeddings,
                )
            return F.layer_norm(hidden_states, hidden_states.shape[-1:])
        hidden_states = self.model(pixel_values=image).last_hidden_state
        return F.layer_norm(hidden_states, hidden_states.shape[-1:])
'''


def _replace(path: Path, old: str, new: str, already: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if already in text:
        print(f"{label}: already patched", flush=True)
        return
    if old not in text:
        raise SystemExit(f"{label}: pattern not found in {path}")
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"{label}: patched", flush=True)


def main() -> None:
    _replace(
        ROOT / "trellis2/pipelines/trellis2_image_to_3d.py",
        REMBG_OLD,
        REMBG_NEW,
        "pipeline.rembg_model = None",
        "rembg_i23d",
    )
    _replace(
        ROOT / "trellis2/pipelines/trellis2_texturing.py",
        REMBG_OLD,
        REMBG_NEW,
        "pipeline.rembg_model = None",
        "rembg_tex",
    )
    _replace(
        ROOT / "trellis2/modules/image_feature_extractor.py",
        DINO_OLD,
        DINO_NEW,
        "layer_root = self.model if hasattr(self.model, \"layer\")",
        "dino",
    )
    _replace(
        ROOT / "trellis2/pipelines/trellis2_image_to_3d.py",
        REMBG_TO_OLD,
        REMBG_TO_NEW,
        "if self.rembg_model is not None:",
        "rembg_to_i23d",
    )


if __name__ == "__main__":
    main()
