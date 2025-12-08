import os
import asyncpg
from datetime import datetime
from typing import Dict, List, Optional, Any
from app.logger import logger

class Database:
    def __init__(self):
        self.pool = None
        self.database_url = os.getenv("DATABASE_URL")
        
    async def connect(self):
        """Connect to PostgreSQL"""
        if not self.pool and self.database_url:
            try:
                self.pool = await asyncpg.create_pool(
                    self.database_url,
                    min_size=1,
                    max_size=10,
                    command_timeout=60
                )
                await self._init_tables()
                logger.info("✅ Connected to PostgreSQL")
            except Exception as e:
                logger.error(f"PostgreSQL connection failed: {e}")
                raise
    
    async def _init_tables(self):
        """Initialize database tables"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS client_memory (
                    id SERIAL PRIMARY KEY,
                    client_id VARCHAR(100) NOT NULL,
                    memory_type VARCHAR(50) NOT NULL,
                    key VARCHAR(255) NOT NULL,
                    value TEXT NOT NULL,
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(client_id, memory_type, key)
                );
                
                CREATE INDEX IF NOT EXISTS idx_client_memory_client ON client_memory(client_id);
                CREATE INDEX IF NOT EXISTS idx_client_memory_type ON client_memory(memory_type);
                
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id SERIAL PRIMARY KEY,
                    client_id VARCHAR(100) NOT NULL,
                    task_id VARCHAR(100) NOT NULL,
                    analysis_type VARCHAR(50) NOT NULL,
                    input_data TEXT NOT NULL,
                    result_data TEXT NOT NULL,
                    insights JSONB,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                
                CREATE INDEX IF NOT EXISTS idx_analysis_client ON analysis_history(client_id);
                CREATE INDEX IF NOT EXISTS idx_analysis_created ON analysis_history(created_at);
            ''')
    
    async def store_memory(self, client_id: str, memory_type: str, 
                          key: str, value: str, metadata: Optional[Dict] = None):
        """Store memory for client"""
        await self.connect()
        
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO client_memory (client_id, memory_type, key, value, metadata, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (client_id, memory_type, key) 
                DO UPDATE SET value = $4, metadata = $5, updated_at = NOW()
            ''', client_id, memory_type, key, value, metadata)
    
    async def get_memory(self, client_id: str, memory_type: str, key: str) -> Optional[Dict]:
        """Retrieve memory for client"""
        await self.connect()
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT * FROM client_memory 
                WHERE client_id = $1 AND memory_type = $2 AND key = $3
            ''', client_id, memory_type, key)
            
            if row:
                return dict(row)
            return None
    
    async def get_client_memories(self, client_id: str, memory_type: Optional[str] = None) -> List[Dict]:
        """Get all memories for a client"""
        await self.connect()
        
        async with self.pool.acquire() as conn:
            if memory_type:
                rows = await conn.fetch('''
                    SELECT * FROM client_memory 
                    WHERE client_id = $1 AND memory_type = $2
                    ORDER BY updated_at DESC
                ''', client_id, memory_type)
            else:
                rows = await conn.fetch('''
                    SELECT * FROM client_memory 
                    WHERE client_id = $1
                    ORDER BY updated_at DESC
                ''', client_id)
            
            return [dict(row) for row in rows]
    
    async def save_analysis(self, client_id: str, task_id: str, 
                           analysis_type: str, input_data: Dict, 
                           result_data: Dict, insights: Optional[Dict] = None):
        """Save analysis to history"""
        await self.connect()
        
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO analysis_history 
                (client_id, task_id, analysis_type, input_data, result_data, insights)
                VALUES ($1, $2, $3, $4, $5, $6)
            ''', client_id, task_id, analysis_type, 
                 str(input_data), str(result_data), insights)
    
    async def get_analysis_history(self, client_id: str, limit: int = 10) -> List[Dict]:
        """Get analysis history for client"""
        await self.connect()
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM analysis_history 
                WHERE client_id = $1
                ORDER BY created_at DESC
                LIMIT $2
            ''', client_id, limit)
            
            return [dict(row) for row in rows]

# Global instance
database = Database()