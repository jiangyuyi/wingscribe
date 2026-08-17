from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    slug: str
    hub_model_id: str
    architecture: str
    license: str
    experimental: bool = False


MODEL_REGISTRY = {
    "bioclip": ModelSpec(
        slug="bioclip",
        hub_model_id="hf-hub:imageomics/bioclip",
        architecture="ViT-B-16",
        license="MIT",
    ),
    "bioclip-2": ModelSpec(
        slug="bioclip-2",
        hub_model_id="hf-hub:imageomics/bioclip-2",
        architecture="ViT-L-14",
        license="MIT",
    ),
    "bioclip-2.5-vith14": ModelSpec(
        slug="bioclip-2.5-vith14",
        hub_model_id="hf-hub:imageomics/bioclip-2.5-vith14",
        architecture="ViT-H-14",
        license="MIT",
        experimental=True,
    ),
}


def get_model_spec(model_name: str) -> ModelSpec:
    normalized = str(model_name).strip().lower()
    try:
        return MODEL_REGISTRY[normalized]
    except KeyError as exc:
        supported = ", ".join(MODEL_REGISTRY)
        raise ValueError(f"Unsupported local recognition model {model_name!r}. Supported: {supported}") from exc
