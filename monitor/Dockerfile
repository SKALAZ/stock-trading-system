# 모니터링 화면 + API를 컨테이너 하나로.
# 1단계(node)에서 Vue를 빌드하고, 2단계(python)에서 API가 빌드된 화면까지 함께 서빙한다.
# 내 PC에는 Node.js가 없어도 된다.

FROM node:20-alpine AS web
WORKDIR /web
COPY monitor/web/package.json ./
RUN npm install --no-audit --no-fund
COPY monitor/web/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app STATIC_DIR=/app/static
WORKDIR /app
COPY monitor/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY monitor/api/main.py /app/monitor_api.py
COPY --from=web /web/dist /app/static
# trader 코드·설정·원칙·기록은 docker-compose.yml 에서 읽기 전용으로 붙인다 (.env 는 붙이지 않는다)
EXPOSE 8000
CMD ["uvicorn", "monitor_api:app", "--host", "0.0.0.0", "--port", "8000"]
