# The game-server image: the launcher and every match server run from it. The same image is
# what a fleet service would run later (one match per container).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /game
COPY game/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Assets before code, so a code-only deploy reuses the cached asset layers.
COPY game/Graphics ./Graphics
COPY game/Audio ./Audio
COPY game/levels ./levels
COPY game/Server ./Server
COPY game/Code ./Code
# Game files stay root-owned and read-only; only logs/ is writable by the runtime user.
RUN mkdir -p logs/matches && useradd --create-home --uid 10001 prch && chown -R prch:prch /game/logs
USER prch
ENV SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy PYTHONUNBUFFERED=1
