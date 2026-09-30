# Signalpost agent: every dependency is installed at build time; the container needs network
# only to reach the public sources (data.brreg.no and company websites) at run time.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY signalpost ./signalpost
COPY tests ./tests
RUN python -m pytest -q
EXPOSE 8000
ENTRYPOINT ["python", "-m", "signalpost"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000", "--state-dir", "/data/ui-state"]
