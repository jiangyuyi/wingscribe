"""Run a local JPEG culling task into an explicitly selected SQLite database."""
import argparse
import hashlib
import json
from pathlib import Path
import signal
import sys
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--backup-dir',type=Path,required=True)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--device',default='cpu')
    parser.add_argument('--gap',type=float,required=True)
    parser.add_argument('--span',type=float,required=True)
    parser.add_argument('--request-key',default=None)
    args=parser.parse_args()
    if not args.model.is_file() or not args.source.is_dir():
        parser.error('Existing local model and source directory are required')
    from src.storage.catalogue import AssetCatalogue
    from src.storage.culling import CullingStore
    from src.application.culling import CullingService
    from ultralytics import YOLO
    import numpy as np
    catalogue=AssetCatalogue(args.db)
    catalogue.initialize(backup_dir=args.backup_dir)
    store=CullingStore(args.db);store.initialize(backup_dir=args.backup_dir)
    with args.model.open('rb') as stream:
        model_hash=hashlib.file_digest(stream,'sha256').hexdigest()
    model=YOLO(str(args.model))
    def detect(frame):
        predictions=model.predict(source=np.ascontiguousarray(frame.pixels[:,:,::-1]),
                                  conf=0.5,classes=[14],imgsz=640,device=args.device,verbose=False)
        return [box.xyxy[0].tolist() for prediction in predictions for box in prediction.boxes]
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGINT,stop)
    result=CullingService(catalogue,store,detect,detector_identity=dict(
        sha256=model_hash,imgsz=640,confidence=0.5,classes=[14],device=args.device)).run(
            args.source,request_key=args.request_key or uuid4().hex,gap=args.gap,span=args.span,
            cancelled=lambda:stopped)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='completed' else 2


if __name__=='__main__':
    raise SystemExit(main())
