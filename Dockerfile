FROM python:3.12-alpine

WORKDIR /app
COPY server.py .

ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python3 -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/healthz', timeout=3)"

CMD ["python3", "server.py"]
