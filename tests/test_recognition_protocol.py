import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.recognition.protocol import (
    BatchRecognizeRequest, BatchRecognizeResponse, BatchResultResponse,
    RecognizeRequest, RecognizeResponse,
)


@pytest.mark.parametrize('model', [RecognizeRequest, RecognizeResponse,
                                  BatchRecognizeRequest, BatchRecognizeResponse,
                                  BatchResultResponse])
def test_documented_examples_are_valid_json_and_model_values(model):
    schema = json.loads(json.dumps(model.model_json_schema()))
    value = model.model_validate(schema['example'])
    assert json.loads(value.model_dump_json())


def test_recognition_openapi_endpoint_serializes_all_response_schemas():
    from src.web.routes.recognition import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get('/openapi.json')
    assert response.status_code == 200
    schemas = response.json()['components']['schemas']
    assert schemas['BatchResultResponse']['example']['created_at']
    assert schemas['RecognizeRequest']['properties']['top_k']['maximum'] == 20
