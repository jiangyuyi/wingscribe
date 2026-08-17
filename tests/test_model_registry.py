import pytest

from src.recognition.model_registry import MODEL_REGISTRY, get_model_spec


def test_registry_contains_supported_bioclip_architectures():
    assert get_model_spec("bioclip").architecture == "ViT-B-16"
    assert get_model_spec("BIOCLIP-2").architecture == "ViT-L-14"
    assert get_model_spec("bioclip-2.5-vith14").architecture == "ViT-H-14"


def test_bioclip_25_is_explicitly_experimental():
    spec = MODEL_REGISTRY["bioclip-2.5-vith14"]

    assert spec.experimental is True
    assert spec.hub_model_id == "hf-hub:imageomics/bioclip-2.5-vith14"
    assert spec.license == "MIT"


def test_unknown_model_does_not_silently_fall_back():
    with pytest.raises(ValueError, match="Unsupported local recognition model"):
        get_model_spec("bioclip-typo")
