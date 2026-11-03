"""Portable entry point; configuration is managed only by the Web UI."""
import argparse
import os
from pathlib import Path
import sys
import logging
import threading
import webbrowser


def open_when_ready(server, runtime, host, port, settings, stopped):
    """Open only this server's ready instance, after startup and socket binding."""
    while not stopped.wait(0.1):
        if not server.started:
            continue
        browser_host = '127.0.0.1' if host == '0.0.0.0' else ('::1' if host == '::' else host)
        if ':' in browser_host:
            browser_host = f'[{browser_host}]'
        page = '/settings' if settings or not runtime.is_paths_configured() else '/'
        url = f'http://{browser_host}:{port}{page}'
        try:
            if not webbrowser.open(url):
                logging.warning('请在浏览器打开 %s', url)
        except Exception:
            logging.warning('无法自动打开浏览器，请手动打开 %s', url)
        return


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--config-guide', action='store_true', help='Open the normal Web configuration flow')
    parser.add_argument('--no-browser', action='store_true', help='Start without opening a browser')
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
    server = uvicorn.Server(uvicorn.Config(application, host=host, port=port))
    stopped = threading.Event()
    browser = None
    if not args.no_browser:
        browser = threading.Thread(target=open_when_ready,
            args=(server, runtime, host, port, args.config_guide, stopped), daemon=True)
        browser.start()
    try:
        server.run()
    finally:
        stopped.set()
        if browser is not None:
            browser.join(timeout=1)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
