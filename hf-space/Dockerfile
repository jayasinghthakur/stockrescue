# Single-container deployment for Hugging Face Spaces:
# FalkorDB + the Streamlit app in one image.
FROM falkordb/falkordb:latest

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py agent.py start.sh ./
# The base image has no useradd; create the uid-1000 user by hand
# (Hugging Face Spaces runs containers as uid 1000).
RUN chmod +x start.sh && \
    echo "appuser:x:1000:1000::/home/appuser:/bin/sh" >> /etc/passwd && \
    echo "appuser:x:1000:" >> /etc/group && \
    mkdir -p /data /home/appuser && \
    chown -R 1000:1000 /data /app /home/appuser

USER appuser
EXPOSE 7860

# Bypass the base image's own startup script; start.sh runs redis+app itself.
ENTRYPOINT []
CMD ["./start.sh"]
