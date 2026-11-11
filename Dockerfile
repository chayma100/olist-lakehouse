FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg
COPY requirements-agent.txt .
RUN pip install --no-cache-dir -r requirements-agent.txt
COPY agent ./agent
COPY api ./api
# Les secrets ne sont jamais dans l'image : ils arrivent par variables d'environnement.
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
