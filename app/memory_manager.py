import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import redis.asyncio as redis
from app.database import database
from app.logger import logger

class MemoryManager:
    def __init__(self):
        self.redis_client = None
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        
    async def connect_redis(self):
        """Connect to Redis for short-term memory"""
        if not self.redis_client:
            self.redis_client = await redis.from_url(
                self.redis_url,
                decode_responses=True
            )
    
    # Short-term memory (Redis, expires in 24h)
    async def set_short_term(self, client_id: str, key: str, value: Any, ttl: int = 86400):
        """Store short-term memory (24h default)"""
        await self.connect_redis()
        await self.redis_client.setex(
            f"memory:{client_id}:{key}",
            ttl,
            json.dumps(value)
        )
    
    async def get_short_term(self, client_id: str, key: str) -> Optional[Any]:
        """Get short-term memory"""
        await self.connect_redis()
        data = await self.redis_client.get(f"memory:{client_id}:{key}")
        return json.loads(data) if data else None
    
    # Long-term memory (PostgreSQL, permanent)
    async def set_long_term(self, client_id: str, memory_type: str, 
                           key: str, value: Any, metadata: Optional[Dict] = None):
        """Store long-term memory"""
        await database.store_memory(
            client_id=client_id,
            memory_type=memory_type,
            key=key,
            value=json.dumps(value),
            metadata=metadata
        )
    
    async def get_long_term(self, client_id: str, memory_type: str, key: str) -> Optional[Any]:
        """Get long-term memory"""
        memory = await database.get_memory(client_id, memory_type, key)
        if memory:
            return json.loads(memory['value'])
        return None
    
    async def get_client_context(self, client_id: str) -> str:
        """Get combined context for client (short + long term)"""
        context_parts = []
        
        # Get long-term memories
        long_term_memories = await database.get_client_memories(client_id)
        for memory in long_term_memories[:5]:  # Last 5 memories
            try:
                value = json.loads(memory['value'])
                context_parts.append(
                    f"[{memory['memory_type']}: {memory['key']}] {value}"
                )
            except:
                pass
        
        # Get recent analysis history
        history = await database.get_analysis_history(client_id, limit=3)
        for item in history:
            context_parts.append(
                f"[History: {item['analysis_type']}] Input: {item['input_data'][:100]}..."
            )
        
        return "\n".join(context_parts) if context_parts else "No previous context found."
    
    async def learn_from_analysis(self, client_id: str, task_id: str, 
                                 analysis_type: str, input_data: Dict, 
                                 result_data: Dict, key_insights: List[str]):
        """Learn and store insights from analysis"""
        # Save to history
        await database.save_analysis(
            client_id=client_id,
            task_id=task_id,
            analysis_type=analysis_type,
            input_data=input_data,
            result_data=result_data,
            insights={"key_insights": key_insights}
        )
        
        # Store key insights as long-term memory
        for i, insight in enumerate(key_insights[:3]):  # Top 3 insights
            await self.set_long_term(
                client_id=client_id,
                memory_type="insight",
                key=f"insight_{task_id}_{i}",
                value={
                    "insight": insight,
                    "source_analysis": analysis_type,
                    "task_id": task_id
                }
            )
        
        logger.info(f"Learned {len(key_insights)} insights for client {client_id}")

# Global instance
memory_manager = MemoryManager()