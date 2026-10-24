"""Portable entry point; configuration is managed only by the Web UI."""
import argparse
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--config-guide', action='store_true', help='Open the normal Web configuration flow')
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ['PATH'] = os.pathsep.join([
        str(root / 'python'), str(root / 'python/Scripts'),
        str(root / 'python/Lib/site-packages/torch/lib'), str(root / 'tools'),
        os.environ.get('PATH', ''),
    ])
    # Keep model-library preferences local, including on the first launch.
    preferences = root / 'data/runtime-config'
    preferences.mkdir(parents=True, exist_ok=True)
    os.environ['YOLO_CONFIG_DIR'] = str(preferences)
    import torch
    from src.web.app import create_app
    application = create_app()
    if args.self_test:
        print(f'Web application self-test passed; torch={torch.__version__}')
        return 0
    import uvicorn
    runtime = application.state.runtime
    host = args.host or runtime.config['web']['host']
    port = args.port if args.port is not None else runtime.config['web']['port']
    runtime._startup_host = host
    runtime._startup_port = port
    uvicorn.run(application, host=host, port=port)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
