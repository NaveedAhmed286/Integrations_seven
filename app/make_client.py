import os
import aiohttp
import json
from datetime import datetime
from typing import Dict, List, Optional
from app.logger import logger

class MakeClient:
    def __init__(self):
        self.webhook_url = os.getenv("MAKE_WEBHOOK_URL")
        self.api_key = os.getenv("MAKE_API_KEY")
        
        if self.webhook_url:
            logger.info("Make.com client initialized")
        else:
            logger.warning("MAKE_WEBHOOK_URL not configured - Make.com integration disabled")
    
    async def send_product_analysis_result(self, result: Dict) -> bool:
        """
        Send product analysis results to Make.com
        Triggered when client provides investment & price
        """
        if not self.webhook_url:
            logger.warning("Make.com webhook URL not configured, skipping send")
            return False
        
        try:
            payload = {
                "event_type": "product_analysis_complete",
                "client_id": result.get("client_id"),
                "success": result.get("success", False),
                "analysis_type": "product_analysis",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "products_analyzed": len(result.get("analyzed_products", [])),
                    "total_investment": result.get("total_investment"),
                    "risk_level": result.get("risk_level"),
                    "estimated_profit": result.get("estimated_profit"),
                    "recommendations": result.get("recommendations", []),
                    "top_product": result.get("top_product")
                }
            }
            
            if not result.get("success"):
                payload["error"] = result.get("error", "Unknown error")
            
            success = await self._send_to_webhook(payload)
            
            if success:
                logger.info(f"Product analysis sent to Make.com for client {result.get('client_id')}")
            else:
                logger.error(f"Failed to send product analysis to Make.com")
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending product analysis to Make.com: {e}")
            return False
    
    async def send_keyword_analysis_result(self, result: Dict) -> bool:
        """
        Send keyword analysis results to Make.com
        Triggered when client provides only product description
        """
        if not self.webhook_url:
            logger.warning("Make.com webhook URL not configured, skipping send")
            return False
        
        try:
            payload = {
                "event_type": "keyword_analysis_complete",
                "client_id": result.get("client_id"),
                "keyword": result.get("keyword"),
                "success": result.get("success", False),
                "analysis_type": "keyword_analysis",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "total_products_found": result.get("total_products_found", 0),
                    "scraping_stats": result.get("scraping_stats", {}),
                    "market_size": result.get("ai_analysis", {}).get("market_size"),
                    "competition_level": result.get("ai_analysis", {}).get("competition_level"),
                    "profit_potential": result.get("ai_analysis", {}).get("profit_potential"),
                    "top_keyword_suggestions": result.get("ai_analysis", {}).get("keyword_suggestions", []),
                    "top_products": result.get("top_products", [])[:5]
                }
            }
            
            if not result.get("success"):
                payload["error"] = result.get("error", "Unknown error")
            
            success = await self._send_to_webhook(payload)
            
            if success:
                logger.info(f"Keyword analysis sent to Make.com for client {result.get('client_id')}")
            else:
                logger.error(f"Failed to send keyword analysis to Make.com")
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending keyword analysis to Make.com: {e}")
            return False
    
    async def send_amazon_scraping_results(self, result: Dict) -> bool:
        """
        Send raw Amazon scraping results to Make.com
        For direct scraping requests
        """
        if not self.webhook_url:
            logger.warning("Make.com webhook URL not configured, skipping send")
            return False
        
        try:
            payload = {
                "event_type": "amazon_scraping_complete",
                "client_id": result.get("client_id"),
                "keyword": result.get("keyword"),
                "success": result.get("success", False),
                "analysis_type": "scraping_only",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "total_products": result.get("total_products", 0),
                    "statistics": result.get("statistics", {}),
                    "category_used": result.get("category_used"),
                    "run_id": result.get("run_id"),
                    "scraper_used": result.get("scraper_used"),
                    "top_products": result.get("products", [])[:3]
                }
            }
            
            if not result.get("success"):
                payload["error"] = result.get("error", "Unknown error")
            
            success = await self._send_to_webhook(payload)
            
            if success:
                logger.info(f"Amazon scraping results sent to Make.com for client {result.get('client_id')}")
            else:
                logger.error(f"Failed to send Amazon scraping results to Make.com")
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending Amazon scraping to Make.com: {e}")
            return False
    
    async def send_error_notification(self, client_id: str, error_message: str, context: Dict = None) -> bool:
        """
        Send error notification to Make.com
        """
        if not self.webhook_url:
            logger.warning("Make.com webhook URL not configured, skipping error notification")
            return False
        
        try:
            payload = {
                "event_type": "agent_error",
                "client_id": client_id,
                "success": False,
                "error": error_message,
                "timestamp": datetime.now().isoformat(),
                "context": context or {}
            }
            
            success = await self._send_to_webhook(payload)
            
            if success:
                logger.info(f"Error notification sent to Make.com for client {client_id}")
            else:
                logger.error(f"Failed to send error notification to Make.com")
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending error notification to Make.com: {e}")
            return False
    
    async def _send_to_webhook(self, payload: Dict) -> bool:
        """
        Internal method to send data to Make.com webhook
        """
        try:
            headers = {
                "Content-Type": "application/json"
            }
            
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    headers=headers
                ) as response:
                    if response.status in [200, 201, 202]:
                        return True
                    else:
                        response_text = await response.text()
                        logger.error(f"Make.com webhook returned {response.status}: {response_text}")
                        return False
                        
        except asyncio.TimeoutError:
            logger.error("Timeout sending to Make.com webhook")
            return False
        except Exception as e:
            logger.error(f"Error sending to Make.com webhook: {e}")
            return False
    
    async def test_connection(self) -> bool:
        """
        Test connection to Make.com webhook
        """
        if not self.webhook_url:
            return False
        
        try:
            test_payload = {
                "event_type": "connection_test",
                "timestamp": datetime.now().isoformat(),
                "message": "Testing connection from Amazon AI Agent"
            }
            
            return await self._send_to_webhook(test_payload)
        except Exception as e:
            logger.error(f"Make.com connection test failed: {e}")
            return False

# Singleton instance
make_client = MakeClient()
