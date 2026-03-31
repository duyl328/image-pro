  启动方式

  # 后端
  cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8000

  # 前端
  cd frontend && npm install && npm run dev