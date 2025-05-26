# [Source: 13]
FROM python:3.12-slim

WORKDIR /app/DRIM_AI # Changed from OpenManus

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    # Added for Playwright browser dependencies
    xvfb \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libgtk-3-0 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install uv if not present, or upgrade pip
RUN command -v uv >/dev/null 2>&1 || pip install --no-cache-dir uv

COPY requirements.txt .
# Install python dependencies
RUN uv pip install --system --no-cache-dir -r requirements.txt

# Install Playwright browsers
# browser-use (which uses Playwright) should ideally handle this,
# but explicit installation in Docker can be more reliable.
# Check browser-use documentation for best practices in Docker.
# RUN playwright install --with-deps chromium # Example for chromium

COPY . .

# Create a default workspace directory if it's used by the application
RUN mkdir -p workspace

CMD ["bash"]