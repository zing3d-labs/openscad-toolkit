FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/zing3d-labs/openscad-toolkit"
LABEL org.opencontainers.image.description="OpenSCAD compiler tools"
LABEL org.opencontainers.image.licenses="CC-BY-NC-SA-4.0"

COPY dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

WORKDIR /work
ENTRYPOINT ["scad-compiler"]
