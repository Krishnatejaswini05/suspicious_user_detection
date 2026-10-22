# The public demo: the reviewer dashboard over simulated users (no real people).
#   docker build -t riskdetect-demo .
#   docker run -p 7860:7860 riskdetect-demo      ->  http://localhost:7860
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Run as an ordinary user (uid 1000, as Hugging Face Spaces expects), never as root.
RUN useradd --create-home --uid 1000 app
WORKDIR /home/app/riskdetect

COPY --chown=app:app pyproject.toml README.md ./
COPY --chown=app:app src ./src
RUN pip install .

COPY --chown=app:app configs ./configs
COPY --chown=app:app deploy ./deploy
USER app
# Simulate users and run the pipeline at build time, so the site starts in seconds.
RUN sh deploy/build_demo_data.sh

EXPOSE 7860
CMD ["python", "-m", "riskdetect.serving", "--demo", "--host", "0.0.0.0", "--port", "7860", \
     "--platform", "synthetic_forum", "--platform", "synthetic_chat", "--platform", "synthetic_market"]
