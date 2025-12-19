import os
import json
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
import redis.asyncio as redis
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.logger import logger

class QueueManager:
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self.redis_client = None
        self.queue_key = "amazon_ai_queue"
        self.results_key = "amazon_ai_results"
        self.tasks_key = "amazon_ai_tasks"
        self.max_retries = 5
        self.retry_delay = 2
        
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((redis.ConnectionError, redis.TimeoutError)),
        reraise=True
    )
    async def connect(self):
        """Connect to Redis with automatic retry"""
        if not self.redis_client:
            try:
                self.redis_client = await redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=10,
                    socket_keepalive=True,
                    retry_on_timeout=True,
                    max_connections=10
                )
                # Test connection
                await self.redis_client.ping()
                logger.info(f"✅ Connected to Redis: {self.redis_url}")
            except Exception as e:
                logger.error(f"❌ Redis connection failed: {e}")
                self.redis_client = None
                raise
    
    async def ensure_connection(self):
        """Ensure Redis connection is active, reconnect if needed"""
        try:
            if not self.redis_client:
                await self.connect()
                return True
                
            # Test existing connection
            await self.redis_client.ping()
            return True
            
        except (redis.ConnectionError, redis.TimeoutError, AttributeError):
            logger.warning("🔄 Redis connection lost, attempting to reconnect...")
            self.redis_client = None
            try:
                await self.connect()
                return True
            except Exception as e:
                logger.error(f"❌ Failed to reconnect to Redis: {e}")
                return False
        except Exception as e:
            logger.error(f"❌ Unexpected Redis error: {e}")
            return False
    
    async def add_task(self, task_id: str, task_type: str, client_id: str, 
                      data: Dict, priority: str = "normal", callback_url: Optional[str] = None) -> bool:
        """Add task to queue with resilience"""
        if not await self.ensure_connection():
            logger.error("Cannot add task: Redis unavailable")
            return False
        
        task_data = {
            "task_id": task_id,
            "type": task_type,
            "client_id": client_id,
            "data": data,
            "priority": priority,
            "callback_url": callback_url,
            "status": "queued",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        try:
            # Store task info
            await self.redis_client.hset(self.tasks_key, task_id, json.dumps(task_data))
            
            # Add to queue (priority queue)
            score = 1 if priority == "high" else 2  # Lower score = higher priority
            await self.redis_client.zadd(self.queue_key, {task_id: score})
            
            logger.info(f"✅ Task added to queue: {task_id} (priority: {priority})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error adding task: {e}")
            return False
    
    async def get_next_task(self) -> Optional[Dict]:
        """Get next task from queue (FIFO with priority) with resilience"""
        if not await self.ensure_connection():
            logger.error("Cannot get next task: Redis unavailable")
            return None
        
        try:
            # Get task with highest priority (lowest score)
            task_ids = await self.redis_client.zrange(self.queue_key, 0, 0)
            
            if not task_ids:
                return None
            
            task_id = task_ids[0]
            
            # Remove from queue
            removed = await self.redis_client.zrem(self.queue_key, task_id)
            if removed != 1:
                logger.warning(f"Task {task_id} was already removed from queue")
                return None
            
            # Get task data
            task_json = await self.redis_client.hget(self.tasks_key, task_id)
            if task_json:
                task_data = json.loads(task_json)
                task_data["status"] = "processing"
                task_data["updated_at"] = datetime.utcnow().isoformat()
                
                # Update task status
                await self.redis_client.hset(self.tasks_key, task_id, json.dumps(task_data))
                
                logger.info(f"🔄 Processing task: {task_id}")
                return task_data
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Error getting next task: {e}")
            return None
    
    async def save_task_result(self, task_id: str, client_id: str, task_type: str, 
                             results: Dict, callback_url: Optional[str] = None):
        """Save task results with resilience"""
        if not await self.ensure_connection():
            logger.error(f"Cannot save results for task {task_id}: Redis unavailable")
            return
        
        result_data = {
            "task_id": task_id,
            "client_id": client_id,
            "type": task_type,
            "results": results,
            "completed_at": datetime.utcnow().isoformat(),
            "status": results.get("status", "completed")
        }
        
        try:
            # Store result
            await self.redis_client.hset(self.results_key, task_id, json.dumps(result_data))
            
            # Update task status
            task_json = await self.redis_client.hget(self.tasks_key, task_id)
            if task_json:
                task_data = json.loads(task_json)
                task_data["status"] = "completed"
                task_data["updated_at"] = datetime.utcnow().isoformat()
                await self.redis_client.hset(self.tasks_key, task_id, json.dumps(task_data))
            
            logger.info(f"✅ Results saved for task: {task_id}")
            
            # Trigger callback if URL provided
            if callback_url:
                asyncio.create_task(self._trigger_callback(callback_url, result_data))
                
        except Exception as e:
            logger.error(f"❌ Error saving results: {e}")
    
    async def get_task_result(self, task_id: str) -> Optional[Dict]:
        """Get task results with resilience"""
        if not await self.ensure_connection():
            logger.error(f"Cannot get result for task {task_id}: Redis unavailable")
            return None
        
        try:
            result_json = await self.redis_client.hget(self.results_key, task_id)
            if result_json:
                return json.loads(result_json)
            return None
        except Exception as e:
            logger.error(f"❌ Error getting results: {e}")
            return None
    
    async def get_task_info(self, task_id: str) -> Optional[Dict]:
        """Get task information with resilience"""
        if not await self.ensure_connection():
            logger.error(f"Cannot get info for task {task_id}: Redis unavailable")
            return None
        
        try:
            task_json = await self.redis_client.hget(self.tasks_key, task_id)
            if task_json:
                return json.loads(task_json)
            return None
        except Exception as e:
            logger.error(f"❌ Error getting task info: {e}")
            return None
    
    async def get_queue_position(self, task_id: str) -> int:
        """Get position in queue with resilience"""
        if not await self.ensure_connection():
            logger.error("Cannot get queue position: Redis unavailable")
            return -1
        
        try:
            position = await self.redis_client.zrank(self.queue_key, task_id)
            return position + 1 if position is not None else 0
        except Exception as e:
            logger.error(f"❌ Error getting queue position: {e}")
            return -1
    
    async def get_queue_size(self) -> int:
        """Get current queue size with resilience"""
        if not await self.ensure_connection():
            logger.error("Cannot get queue size: Redis unavailable")
            return -1
        
        try:
            return await self.redis_client.zcard(self.queue_key)
        except Exception as e:
            logger.error(f"❌ Error getting queue size: {e}")
            return -1
    
    async def get_queue_stats(self) -> Dict:
        """Get queue statistics with resilience"""
        if not await self.ensure_connection():
            logger.error("Cannot get queue stats: Redis unavailable")
            return {"error": "Redis unavailable", "queue_size": -1}
        
        try:
            queue_size = await self.get_queue_size()
            
            # Get recent tasks
            all_tasks = await self.redis_client.hgetall(self.tasks_key)
            completed_tasks = await self.redis_client.hlen(self.results_key)
            
            stats = {
                "queue_size": queue_size,
                "total_tasks": len(all_tasks),
                "completed_tasks": completed_tasks,
                "pending_tasks": queue_size,
                "processing_tasks": len(all_tasks) - completed_tasks - queue_size,
                "redis_status": "connected"
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"❌ Error getting stats: {e}")
            return {"error": str(e), "queue_size": -1, "redis_status": "disconnected"}
    
    async def update_task_status(self, task_id: str, status: str):
        """Update task status with resilience"""
        if not await self.ensure_connection():
            logger.error(f"Cannot update status for task {task_id}: Redis unavailable")
            return
        
        try:
            task_json = await self.redis_client.hget(self.tasks_key, task_id)
            if task_json:
                task_data = json.loads(task_json)
                task_data["status"] = status
                task_data["updated_at"] = datetime.utcnow().isoformat()
                await self.redis_client.hset(self.tasks_key, task_id, json.dumps(task_data))
                logger.info(f"📝 Updated task {task_id} status to: {status}")
        except Exception as e:
            logger.error(f"❌ Error updating task status: {e}")
    
    async def check_health(self) -> bool:
        """Check Redis connection health with resilience"""
        try:
            if not await self.ensure_connection():
                return False
            await self.redis_client.ping()
            return True
        except Exception as e:
            logger.error(f"❌ Redis health check failed: {e}")
            return False
    
    async def cleanup_old_tasks(self, days: int = 7):
        """Clean up old completed tasks to prevent Redis memory issues"""
        if not await self.ensure_connection():
            return
        
        try:
            cutoff_date = datetime.utcnow().timestamp() - (days * 24 * 60 * 60)
            tasks_to_delete = []
            
            # Get all completed tasks
            all_tasks = await self.redis_client.hgetall(self.tasks_key)
            for task_id, task_json in all_tasks.items():
                try:
                    task_data = json.loads(task_json)
                    if task_data.get("status") == "completed":
                        created_at = datetime.fromisoformat(task_data.get("created_at", "2000-01-01"))
                        if created_at.timestamp() < cutoff_date:
                            tasks_to_delete.append(task_id)
                except:
                    continue
            
            # Delete old tasks
            for task_id in tasks_to_delete:
                await self.redis_client.hdel(self.tasks_key, task_id)
                await self.redis_client.hdel(self.results_key, task_id)
            
            if tasks_to_delete:
                logger.info(f"🧹 Cleaned up {len(tasks_to_delete)} old tasks")
                
        except Exception as e:
            logger.error(f"❌ Error cleaning up old tasks: {e}")
    
    async def _trigger_callback(self, callback_url: str, data: Dict):
        """Trigger callback URL with error handling"""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                async with session.post(callback_url, json=data, timeout=30) as response:
                    if response.status in [200, 201, 202]:
                        logger.info(f"✅ Callback triggered successfully: {callback_url}")
                    else:
                        logger.warning(f"⚠️ Callback failed with status {response.status}: {callback_url}")
                        
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Callback timeout: {callback_url}")
        except Exception as e:
            logger.error(f"❌ Callback error: {e}")

# Global instance
queue_manager = QueueManager()
