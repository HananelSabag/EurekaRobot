"""Run the robot app: python -m server [--sim] [--port 8765]"""

import argparse
import logging

from aiohttp import web

from .app import App

parser = argparse.ArgumentParser(description="Eureka robot local app")
parser.add_argument("--sim", action="store_true", help="use a simulated robot")
parser.add_argument("--port", type=int, default=8765)
parser.add_argument("--host", default="0.0.0.0", help="127.0.0.1 keeps it on this PC only")
args = parser.parse_args()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("midealocal").setLevel(logging.WARNING)
web.run_app(App(args.sim).build(), host=args.host, port=args.port)
