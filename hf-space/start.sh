#!/bin/sh
# Start FalkorDB in the background, wait until it answers, then run the app.
redis-server --loadmodule /var/lib/falkordb/bin/falkordb.so \
             --dir /data --save 60 1 &

until redis-cli ping >/dev/null 2>&1; do
  sleep 0.5
done
echo "FalkorDB is up."

# HF Spaces uses port 7860; Render injects $PORT.
exec streamlit run app.py \
  --server.port="${PORT:-7860}" --server.address=0.0.0.0 \
  --server.headless=true --browser.gatherUsageStats=false
