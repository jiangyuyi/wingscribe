import os
import time
import requests
import logging
import uuid
import hashlib
from typing import List, Dict, Any
from .bioclip_base import BirdRecognizer

class DongniaoRecognizer(BirdRecognizer):
    def __init__(self, api_key: str, api_url: str = "https://ai.open.hhodata.com/api/v2/dongniao"):
        self.api_key = api_key or ""
        self.api_url = api_url or ""
        self.did = hashlib.md5(str(uuid.getnode()).encode()).hexdigest()[:32] # Generate consistent DID based on node
        
        if not self.api_key:
            logging.warning("Dongniao API Key is missing! Recognition will fail.")
        if not self.api_url:
            logging.warning("Dongniao API URL is missing! Recognition will fail.")

    def predict_batch(
        self,
        image_paths: List[str],
        candidate_labels: List[str],
        top_k: int = 5
    ) -> List[List[Dict[str, Any]]]:
        return [
            self.predict(image_path, candidate_labels=candidate_labels, top_k=top_k)
            for image_path in image_paths
        ]

    def predict(self, image_path: str, candidate_labels: List[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Predict using Dongniao API.
        Note: candidate_labels is ignored as Dongniao doesn't support zero-shot candidate restriction.
        """
        if not self.api_key or not self.api_url:
            return []

        try:
            # Step 1: Upload Image
            rec_id = self._upload_image(image_path)
            if not rec_id:
                return []

            # Step 2: Poll for Result
            result = self._poll_result(rec_id)
            if not result:
                return []

            # Step 3: Parse Result
            return self._parse_result(result, top_k)

        except Exception as e:
            logging.error(f"Dongniao API error: {e}")
            return []

    def _upload_image(self, image_path: str) -> str:
        headers = {"api_key": self.api_key}
        
        with open(image_path, 'rb') as f:
            files = {
                'image': (os.path.basename(image_path), f, 'image/jpeg'),
                'upload': (None, '1'),
                'class': (None, 'B'), # Birds only
                'did': (None, self.did)
            }
            
            response = requests.post(self.api_url, headers=headers, files=files, timeout=30)
            status_code = getattr(response, "status_code", 200)
            if status_code != 200:
                logging.error(f"Dongniao upload failed: {status_code} - {response.text}")
                return None
            
            try:
                resp_json = response.json()
            except Exception:
                logging.error(f"Dongniao Upload Response is not JSON: {response.text}")
                return None

            # Handle flat list format: [1000, "ID"]
            if isinstance(resp_json, list):
                if len(resp_json) >= 2 and str(resp_json[0]) == '1000':
                    return resp_json[1]
                logging.error(f"Cannot parse root list response: {resp_json}")
                return None

            if not isinstance(resp_json, dict):
                logging.error(f"Dongniao response is not a dict or list: {type(resp_json)}")
                return None

            # Handle dict format: {"status": "1000", "data": ...}
            if str(resp_json.get('status')) != '1000':
                logging.error(f"Dongniao API returned error: {resp_json.get('message')} (Status: {resp_json.get('status')})")
                return None
                
            data = resp_json.get('data')
            if isinstance(data, list) and len(data) >= 2:
                return data[1]
            elif isinstance(data, dict):
                return data.get('recognitionId')
            
            return None

    def _poll_result(self, rec_id: str, max_retries: int = 10, interval: float = 1.5) -> Dict:
        headers = {"api_key": self.api_key}
        data = {"resultid": rec_id}
        
        for i in range(max_retries):
            time.sleep(interval)
            try:
                response = requests.post(self.api_url, headers=headers, data=data, timeout=10)
                if response.status_code != 200:
                    continue
                
                resp_json = response.json()
                
                # Check for flat list format: [1000, data_list]
                status = None
                data_body = None
                
                if isinstance(resp_json, list):
                    if len(resp_json) >= 2:
                        status = str(resp_json[0])
                        data_body = resp_json[1]
                elif isinstance(resp_json, dict):
                    status = str(resp_json.get('status'))
                    data_body = resp_json.get('data')
                
                if status == '1000': # Success
                    return data_body
                elif status == '1001': # Not ready
                    continue
                elif status in ['1008', '1009']: # No result/No animal
                    logging.info(f"Dongniao: No animal detected (Status {status})")
                    return None
                else:
                    logging.error(f"Dongniao Polling Error: {resp_json}")
                    return None
            except Exception as e:
                logging.warning(f"Polling exception: {e}")
                continue
        
        logging.warning("Dongniao API timed out waiting for results.")
        return None

    def _parse_result(self, data: list, top_k: int) -> List[Dict[str, Any]]:
        # Data structure: [{"box": [...], "list": [[conf, "CN|EN|Sci", id, "B"], ...]}, ...]
        if not data or not isinstance(data, list):
            return []
        
        primary_object = data[0]
        
        # Check if primary_object is dict
        if not isinstance(primary_object, dict):
            logging.error(f"Dongniao Parse Error: Expected dict in data list, got {type(primary_object)}: {primary_object}")
            return []

        prediction_list = primary_object.get('list', [])
        
        results = []
        for item in prediction_list[:top_k]:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                logging.warning(f"Dongniao Parse Warning: Skip malformed item: {item}")
                continue

            # item: [confidence, "NameString", id, "Type"]
            try:
                conf = float(item[0]) / 100.0 # Convert 98.5 -> 0.985
                name_str = str(item[1])
            except (TypeError, ValueError) as exc:
                logging.warning(f"Dongniao Parse Warning: Skip invalid item {item}: {exc}")
                continue
            
            # Parse "Chinese|English|Latin"
            # Example: "北美红松鼠|North American Red Squirrel|Tamiasciurus hudsonicus"
            parts = name_str.split('|')
            scientific_name = parts[-1] if len(parts) >= 3 else parts[0] # Fallback
            
            results.append({
                "scientific_name": scientific_name,
                "confidence": conf
            })
            
        return results
