# Hugging Face Space: builds the demo from the public GitHub repository.
# To pick up new commits, use "Factory rebuild" in the Space's settings.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ARG REPO=https://github.com/Krishnatejaswini05/suspicious_user_detection.git
ARG REF=main

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 app
USER app
WORKDIR /home/app
RUN git clone --depth 1 --branch "$REF" "$REPO" riskdetect
WORKDIR /home/app/riskdetect
RUN pip install --user . && sh deploy/build_demo_data.sh
ENV PATH="/home/app/.local/bin:$PATH"

EXPOSE 7860
CMD ["python", "-m", "riskdetect.serving", "--demo", "--host", "0.0.0.0", "--port", "7860", \
     "--platform", "synthetic_forum", "--platform", "synthetic_chat", "--platform", "synthetic_market"]
