FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY tests/ecommerce_ad ./tests/ecommerce_ad
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN mkdir -p /app/src/db/uploaded_assets /app/src/db/downloaded_assets

EXPOSE 8001
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8001"]
