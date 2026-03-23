import requests
import base64
import logging
from typing import List, Dict, Any
from .bioclip_base import BirdRecognizer

class APIBirdRecognizer(BirdRecognizer):
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def predict_batch(
        self,
        image_paths: List[str],
        candidate_labels: List[str],
        top_k: int = 5
    ) -> List[List[Dict[str, Any]]]:
        return [
            self.predict(image_path, candidate_labels, top_k=top_k)
            for image_path in image_paths
        ]

    def predict(self, image_path: str, candidate_labels: List[str], top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Call Hugging Face Inference API for Zero-Shot Classification.
        """
        if not candidate_labels:
            logging.warning("No candidate labels provided for API inference.")
            return []

        try:
            with open(image_path, "rb") as f:
                image_data = f.read()
                
            # HF API expects base64 inputs for some endpoints, or binary for others.
            # For zero-shot-image-classification with specific candidates, JSON is often safer.
            image_b64 = base64.b64encode(image_data).decode('utf-8')
            
            payload = {
                "inputs": image_b64,
                "parameters": {
                    "candidate_labels": candidate_labels
                }
            }

            response = requests.post(self.api_url, headers=self.headers, json=payload)
            
            if response.status_code != 200:
                logging.error(f"HF API Error: {response.status_code} - {response.text}")
                return []
            
            # Response format: [{"score": 0.99, "label": "label1"}, ...]
            data = response.json()
            
            if not isinstance(data, list):
                logging.error(f"Unexpected HF API response format: {data}")
                return []

            results = []
            for item in data[:top_k]:
                results.append({
                    "scientific_name": item.get("label"),
                    "confidence": item.get("score")
                })
                
            return results

        except Exception as e:
            logging.error(f"API inference failed: {e}")
            return []
