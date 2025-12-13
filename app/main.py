import os
import asyncio
import uuid
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional

from app.logger import logger
from app.queue_manager import QueueManager
from app.agent import AmazonAgent

# Initialize
app = FastAPI(
    title="Amazon AI Queue Agent",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Initialize components
queue_manager = QueueManager()
agent = AmazonAgent()

# Models
class ProductAnalysisRequest(BaseModel):
    client_id: str
    products: List[Dict]
    priority: str = "normal"
    callback_url: Optional[str] = None

class KeywordAnalysisRequest(BaseModel):
    client_id: str
    keyword: str
    max_products: int = 50
    callback_url: Optional[str] = None

@app.on_event("startup")
async def startup_event():
    logger.info("Amazon AI Agent starting up...")
    asyncio.create_task(queue_processor())

@app.get("/")
async def root():
    return {
        "message": "Amazon AI Queue Agent",
        "status": "running",
        "version": "1.0.0",
        "endpoints": {
            "submit_products": "POST /api/analyze/products",
            "submit_keyword": "POST /api/analyze/keyword",
            "check_status": "GET /api/status/{task_id}",
            "queue_stats": "GET /api/queue/stats",
            "docs": "/docs"
        }
    }

@app.post("/api/analyze/products")
async def analyze_products(request: ProductAnalysisRequest):
    try:
        task_id = str(uuid.uuid4())
        await queue_manager.add_task(
            task_id=task_id,
            task_type="product_analysis",
            client_id=request.client_id,
            data={"products": request.products},
            priority=request.priority,
            callback_url=request.callback_url
        )
        logger.info(f"Product analysis queued: {task_id}")
        return {
            "task_id": task_id,
            "status": "queued",
            "message": f"Analysis queued. Check status at /api/status/{task_id}",
            "queue_position": await queue_manager.get_queue_position(task_id)
        }
    except Exception as e:
        logger.error(f"Error submitting products: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze/keyword")
async def analyze_keyword(request: KeywordAnalysisRequest):
    try:
        task_id = str(uuid.uuid4())
        await queue_manager.add_task(
            task_id=task_id,
            task_type="keyword_analysis",
            client_id=request.client_id,
            data={
                "keyword": request.keyword,
                "max_products": request.max_products
            },
            priority="normal",
            callback_url=request.callback_url
        )
        logger.info(f"Keyword analysis queued: {task_id} for '{request.keyword}'")
        return {
            "task_id": task_id,
            "status": "queued",
            "message": f"Keyword analysis queued for '{request.keyword}'"
        }
    except Exception as e:
        logger.error(f"Error submitting keyword: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    try:
        result = await queue_manager.get_task_result(task_id)
        if not result:
            task_info = await queue_manager.get_task_info(task_id)
            if not task_info:
                raise HTTPException(status_code=404, detail="Task not found")
            return {
                "task_id": task_id,
                "status": task_info.get("status", "pending"),
                "position": task_info.get("position"),
                "created_at": task_info.get("created_at")
            }
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/queue/stats")
async def queue_stats():
    try:
        stats = await queue_manager.get_queue_stats()
        return {
            "status": "success",
            "data": stats
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    try:
        queue_size = await queue_manager.get_queue_size()
        redis_status = await queue_manager.check_health()
        return {
            "status": "healthy" if redis_status else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "queue_size": queue_size,
            "redis": "connected" if redis_status else "disconnected",
            "version": "1.0.0"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }

async def queue_processor():
    logger.info("Queue processor started")
    while True:
        try:
            processed = await process_next_task()
            if not processed:
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Queue processor error: {e}")
            await asyncio.sleep(10)

async def process_next_task():
    try:
        task = await queue_manager.get_next_task()
        if not task:
            return False

        task_id = task["task_id"]
        task_type = task["type"]
        client_id = task["client_id"]
        data = task["data"]

        logger.info(f"Processing {task_type}: {task_id}")

        await queue_manager.update_task_status(task_id, "processing")

        if task_type == "product_analysis":
            results = await agent.analyze_products(data["products"])
        elif task_type == "keyword_analysis":
            results = await agent.analyze_keyword(
                keyword=data["keyword"],
                client_id=client_id,
                max_products=data.get("max_products", 50)
            )
        else:
            results = {"error": "Unknown task type", "status": "failed"}

        await queue_manager.save_task_result(
            task_id=task_id,
            client_id=client_id,
            task_type=task_type,
            results=results,
            callback_url=task.get("callback_url")
        )

        logger.info(f"Completed {task_type}: {task_id}")
        return True

    except Exception as e:
        logger.error(f"Task processing failed: {e}")
        if "task_id" in locals():
            await queue_manager.save_task_result(
                task_id=task_id,
                client_id=client_id,
                task_type=task_type,
                results={"error": str(e), "status": "failed"},
                callback_url=task.get("callback_url")
            )
        return False

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
