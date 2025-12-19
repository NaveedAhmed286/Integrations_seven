import os
import asyncio
import uuid
import signal
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional

# Import psutil with fallback
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from app.logger import logger
from app.queue_manager import QueueManager
from app.agent import AmazonAgent

# ========== FASTAPI APP ==========
app = FastAPI(
    title="Amazon AI Queue Agent v2.0",
    description="Resilient Amazon product analysis system with automatic retry and health monitoring",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# ========== GLOBAL STATE ==========
queue_manager = QueueManager()
agent = AmazonAgent()

app_state = {
    "healthy": True,
    "start_time": datetime.utcnow(),
    "total_tasks": 0,
    "failed_tasks": 0,
    "queue_restarts": 0,
    "external_services": {
        "redis": True,
        "google_sheets": True,
        "deepseek": True,
        "apify": True
    },
    "last_health_check": datetime.utcnow(),
    "shutting_down": False
}

# ========== MODELS ==========
class ProductAnalysisRequest(BaseModel):
    client_id: str
    products: List[Dict]
    priority: str = "normal"

class KeywordAnalysisRequest(BaseModel):
    client_id: str
    keyword: str
    max_products: int = 50
    investment: Optional[float] = None

# ========== SIGNAL HANDLING ==========
def handle_shutdown(signum, frame):
    """Handle graceful shutdown signals"""
    if app_state["shutting_down"]:
        return  # Already shutting down
    
    logger.info("🛑 Received shutdown signal, initiating graceful shutdown...")
    app_state["healthy"] = False
    app_state["shutting_down"] = True
    
    # Set a timeout for graceful shutdown
    asyncio.create_task(graceful_shutdown(timeout=30))

async def graceful_shutdown(timeout: int = 30):
    """Wait for current tasks to complete before shutdown with timeout"""
    logger.info(f"⏳ Waiting {timeout} seconds for active tasks to complete...")
    
    try:
        # Wait for timeout or until all tasks are done
        start_time = datetime.utcnow()
        while (datetime.utcnow() - start_time).seconds < timeout:
            # Check if queue is empty or small enough
            queue_size = await queue_manager.get_queue_size()
            if queue_size <= 1:  # Allow 1 task to complete
                break
            await asyncio.sleep(2)
            
        logger.info("✅ Graceful shutdown complete")
    except Exception as e:
        logger.error(f"Shutdown monitoring error: {e}")
    finally:
        # Force exit after timeout
        logger.info("🛑 Shutting down now")
        os._exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

# ========== STARTUP ==========
@app.on_event("startup")
async def startup_event():
    """Initialize all background tasks"""
    logger.info("🚀 Amazon AI Queue Agent v2.0 starting up...")
    
    # Log configuration
    logger.info(f"📊 Log level: {os.getenv('LOG_LEVEL', 'INFO')}")
    
    if not PSUTIL_AVAILABLE:
        logger.warning("⚠️ psutil not installed. Health monitoring limited to basic checks.")
    
    # Start all background services
    asyncio.create_task(queue_processor())
    asyncio.create_task(health_monitor())
    asyncio.create_task(service_health_checker())
    
    logger.info("✅ All background services started")

# ========== HEALTH MONITOR ==========
async def health_monitor():
    """Monitor system resources"""
    while app_state["healthy"]:
        try:
            if PSUTIL_AVAILABLE:
                # Memory usage
                memory = psutil.virtual_memory()
                if memory.percent > 85:
                    logger.warning(f"⚠️ High memory usage: {memory.percent}%")
                
                # CPU usage
                cpu_percent = psutil.cpu_percent(interval=1)
                if cpu_percent > 80:
                    logger.warning(f"⚠️ High CPU usage: {cpu_percent}%")
                
                # Disk space
                disk = psutil.disk_usage('/')
                if disk.percent > 90:
                    logger.warning(f"⚠️ Low disk space: {disk.percent}%")
            else:
                # Simple heartbeat log every 5 minutes
                if datetime.utcnow().minute % 5 == 0:
                    logger.debug("Health monitor heartbeat (psutil not available)")
                
        except Exception as e:
            logger.debug(f"Health monitor error: {e}")
        
        app_state["last_health_check"] = datetime.utcnow()
        await asyncio.sleep(60)  # Check every minute

# ========== SERVICE HEALTH CHECKER ==========
async def service_health_checker():
    """Monitor external service connectivity"""
    while app_state["healthy"]:
        try:
            # Check Redis
            try:
                redis_ok = await queue_manager.check_health()
                app_state["external_services"]["redis"] = redis_ok
                if not redis_ok:
                    logger.error("🔴 Redis connection lost")
            except Exception as e:
                app_state["external_services"]["redis"] = False
                logger.debug(f"Redis health check error: {e}")
            
            # Add more service checks as needed
            
        except Exception as e:
            logger.debug(f"Service health check error: {e}")
        
        await asyncio.sleep(30)  # Check every 30 seconds

# ========== UNBREAKABLE QUEUE PROCESSOR ==========
async def queue_processor():
    """Process tasks from queue - designed to never crash"""
    logger.info("🔄 Starting UNBREAKABLE queue processor...")
    
    consecutive_failures = 0
    max_consecutive_failures = 5
    failure_backoff = 1
    
    while app_state["healthy"]:
        try:
            # Reset failure counter on successful iteration
            consecutive_failures = 0
            failure_backoff = 1
            
            # Process a batch of tasks
            processed = await process_batch()
            
            # Dynamic sleep based on activity
            sleep_time = 5 if processed > 0 else 10
            await asyncio.sleep(sleep_time)
            
        except Exception as e:
            consecutive_failures += 1
            app_state["queue_restarts"] += 1
            
            if consecutive_failures >= max_consecutive_failures:
                logger.critical(f"🚨 Queue processor failed {consecutive_failures} times consecutively. Pausing for 5 minutes.")
                await asyncio.sleep(300)  # 5 minutes
                consecutive_failures = 0
                failure_backoff = 1
            else:
                logger.error(f"⚠️ Queue processor error {consecutive_failures}/{max_consecutive_failures}: {e}")
                failure_backoff = min(failure_backoff * 2, 60)  # Exponential backoff, max 60 seconds
                await asyncio.sleep(failure_backoff)
    
    logger.info("Queue processor stopped (app shutting down)")

async def process_batch() -> int:
    """Process a batch of up to 5 tasks"""
    processed = 0
    
    for _ in range(5):  # Process max 5 tasks per batch
        try:
            task = await queue_manager.get_next_task()
            if not task:
                break  # No more tasks
            
            if await process_single_task(task):
                processed += 1
                
        except Exception as e:
            logger.error(f"Batch processing error: {e}")
            await asyncio.sleep(1)
    
    return processed

async def process_single_task(task: Dict) -> bool:
    """Process a single task with comprehensive error handling"""
    task_id = task.get("task_id", "unknown")
    
    try:
        logger.info(f"🔄 Processing task {task_id}")
        await queue_manager.update_task_status(task_id, "processing")
        
        app_state["total_tasks"] += 1
        
        # Process based on type
        task_type = task.get("type")
        client_id = task.get("client_id")
        data = task.get("data", {})
        
        if task_type == "product_analysis":
            results = await agent.analyze_products(data.get("products", []))
        elif task_type == "keyword_analysis":
            results = await agent.analyze_keyword(
                keyword=data.get("keyword", ""),
                client_id=client_id,
                max_products=data.get("max_products", 50),
                investment=data.get("investment")
            )
        else:
            results = {"error": f"Unknown task type: {task_type}", "status": "failed"}
        
        # Save results
        await queue_manager.save_task_result(
            task_id=task_id,
            client_id=client_id,
            task_type=task_type,
            results=results
        )
        
        logger.info(f"✅ Completed task {task_id}")
        return True
        
    except Exception as e:
        app_state["failed_tasks"] += 1
        logger.error(f"❌ Task {task_id} failed: {e}")
        
        # Save failure result
        try:
            await queue_manager.save_task_result(
                task_id=task_id,
                client_id=task.get("client_id"),
                task_type=task.get("type"),
                results={"error": str(e), "status": "failed"}
            )
        except Exception as save_error:
            logger.error(f"Failed to save task failure: {save_error}")
        
        return True  # Task was "processed" (failed)

# ========== API ENDPOINTS ==========

@app.post("/api/analyze/products")
async def analyze_products(request: ProductAnalysisRequest):
    """Submit products for analysis (direct products data)"""
    try:
        task_id = str(uuid.uuid4())
        
        # Log the request
        logger.info(f"📥 Product analysis request from {request.client_id}")
        logger.info(f"   Products: {len(request.products)}, Priority: {request.priority}")
        
        # Add to queue
        success = await queue_manager.add_task(
            task_id=task_id,
            task_type="product_analysis",
            client_id=request.client_id,
            data={"products": request.products},
            priority=request.priority
        )
        
        if not success:
            logger.error(f"Failed to queue product analysis task: {task_id}")
            raise HTTPException(status_code=500, detail="Failed to queue task")
        
        queue_position = await queue_manager.get_queue_position(task_id)
        
        logger.info(f"✅ Product analysis queued: {task_id} (position: {queue_position})")
        
        return {
            "task_id": task_id,
            "status": "queued",
            "message": f"Product analysis queued. Check status at /api/status/{task_id}",
            "queue_position": queue_position,
            "estimated_wait_seconds": queue_position * 30  # ~30 seconds per task
        }
        
    except Exception as e:
        logger.error(f"❌ Error in analyze_products: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze/keyword")
async def analyze_keyword(request: KeywordAnalysisRequest):
    """Submit keyword for Amazon scraping and analysis"""
    try:
        task_id = str(uuid.uuid4())
        
        # Log the request
        logger.info(f"🔍 Keyword analysis request from {request.client_id}")
        logger.info(f"   Keyword: '{request.keyword}', Max products: {request.max_products}")
        logger.info(f"   Investment: {request.investment}, Priority: normal")
        
        # Add to queue
        success = await queue_manager.add_task(
            task_id=task_id,
            task_type="keyword_analysis",
            client_id=request.client_id,
            data={
                "keyword": request.keyword,
                "max_products": request.max_products,
                "investment": request.investment
            }
        )
        
        if not success:
            logger.error(f"Failed to queue keyword analysis task: {task_id}")
            raise HTTPException(status_code=500, detail="Failed to queue task")
        
        queue_position = await queue_manager.get_queue_position(task_id)
        
        logger.info(f"✅ Keyword analysis queued: {task_id} for '{request.keyword}'")
        
        return {
            "task_id": task_id,
            "status": "queued", 
            "message": f"Keyword analysis queued for '{request.keyword}'. Check status at /api/status/{task_id}",
            "queue_position": queue_position,
            "estimated_wait_seconds": queue_position * 60  # ~60 seconds for scraping
        }
        
    except Exception as e:
        logger.error(f"❌ Error in analyze_keyword: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    """Check status of a task"""
    try:
        result = await queue_manager.get_task_result(task_id)
        if not result:
            task_info = await queue_manager.get_task_info(task_id)
            if not task_info:
                raise HTTPException(status_code=404, detail="Task not found")
            return {
                "task_id": task_id,
                "status": task_info.get("status", "pending"),
                "created_at": task_info.get("created_at"),
                "client_id": task_info.get("client_id")
            }
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/queue/stats")
async def queue_stats():
    """Get queue statistics"""
    try:
        stats = await queue_manager.get_queue_stats()
        return {"status": "success", "data": stats}
    except Exception as e:
        logger.error(f"Error getting queue stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ========== SYSTEM ENDPOINTS ==========

@app.get("/health")
async def health_check():
    """Comprehensive health check"""
    try:
        redis_health = await queue_manager.check_health()
        queue_size = await queue_manager.get_queue_size()
        
        services_ok = all(app_state["external_services"].values())
        queue_healthy = app_state["queue_restarts"] < 10
        
        status = "healthy" if (redis_health and services_ok and queue_healthy) else "degraded"
        
        # Base health data
        health_data = {
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
            "uptime": str(datetime.utcnow() - app_state["start_time"]),
            "resources": {
                "queue_restarts": app_state["queue_restarts"],
                "memory_percent": "unknown",
                "cpu_percent": "unknown",
                "queue_size": queue_size
            },
            "tasks": {
                "total": app_state["total_tasks"],
                "failed": app_state["failed_tasks"],
                "success_rate": f"{((app_state['total_tasks'] - app_state['failed_tasks']) / max(app_state['total_tasks'], 1) * 100):.1f}%"
            },
            "services": app_state["external_services"]
        }
        
        # Add psutil metrics if available
        if PSUTIL_AVAILABLE:
            try:
                health_data["resources"]["memory_percent"] = psutil.virtual_memory().percent
                health_data["resources"]["cpu_percent"] = psutil.cpu_percent(interval=1)
            except Exception as e:
                logger.debug(f"Failed to get system metrics: {e}")
        
        return health_data
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}

@app.get("/")
async def root():
    uptime = datetime.utcnow() - app_state["start_time"]
    return {
        "service": "Amazon AI Queue Agent",
        "version": "2.0.0",
        "status": "operational" if app_state["healthy"] else "shutting_down",
        "uptime": str(uptime),
        "features": [
            "Resilient task processing",
            "Automatic retry on failures",
            "Health monitoring",
            "External service checks",
            "Graceful degradation"
        ],
        "endpoints": {
            "submit_products": "POST /api/analyze/products",
            "submit_keyword": "POST /api/analyze/keyword",
            "check_status": "GET /api/status/{task_id}",
            "queue_stats": "GET /api/queue/stats",
            "system_health": "GET /health",
            "docs": "/docs"
        }
    }

# ========== RUN APPLICATION ==========
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting server on port {port}")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True,
        timeout_keep_alive=30
    )
