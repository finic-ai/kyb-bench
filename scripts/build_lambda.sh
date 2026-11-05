#!/bin/sh
# Build dist/lambda.zip: the kybbench package with its bundled resources and numpy for Lambda
# (python3.12, x86_64). Handler: kybbench.server.handler
set -e
.venv/bin/python scripts/bundle_resources.py
rm -rf dist/lambda dist/lambda.zip && mkdir -p dist/lambda
.venv/bin/pip install -q --target dist/lambda --platform manylinux2014_x86_64 --python-version 3.12 --only-binary=:all: "numpy>=2.0,<3"
cp -r kybbench dist/lambda/
rm -rf dist/lambda/kybbench/__pycache__ dist/lambda/kybbench/*/__pycache__
(cd dist/lambda && zip -qr ../lambda.zip .)
ls -la dist/lambda.zip
