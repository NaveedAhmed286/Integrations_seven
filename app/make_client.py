import os
import json
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional
from app.logger import logger

class MakeClient:
    def __init__(self):
        self.webhook_url = os.getenv("MAKE_WEBHOOK_URL")
        self.api_key = os.getenv("MAKE_API_KEY")
        
    async def send_analysis_results(self, client_id: str, analysis_data: Dict, 
                                   webhook_url: Optional[str] = None) -> bool:
        """
        Send analysis results to Make.com webhook
        """
        try:
            # Use provided webhook URL or default
            url = webhook_url or self.webhook_url
            
            if not url:
                logger.warning("No Make.com webhook URL configured")
                return False
            
            payload = {
                "client_id": client_id,
                "analysis_type": "product_analysis",
                "data": analysis_data,
                "timestamp": datetime.utcnow().isoformat(),
                "status": "completed"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}" if self.api_key else ""
                    },
                    timeout=30
                ) as response:
                    
                    if response.status in [200, 201, 202]:
                        logger.info(f"✅ Results sent to Make.com for client: {client_id}")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Make.com webhook failed: {response.status} - {error_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error sending to Make.com: {e}")
            return False
    
    async def send_keyword_analysis(self, client_id: str, keyword: str, 
                                   analysis_data: Dict, webhook_url: Optional[str] = None) -> bool:
        """
        Send keyword analysis to Make.com
        """
        try:
            url = webhook_url or self.webhook_url
            
            if not url:
                logger.warning("No Make.com webhook URL configured")
                return False
            
            payload = {
                "client_id": client_id,
                "analysis_type": "keyword_analysis",
                "keyword": keyword,
                "data": analysis_data,
                "opportunity_score": analysis_data.get("opportunity_score", 0),
                "recommendations": analysis_data.get("recommendations", []),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=30,
                    headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
                ) as response:
                    
                    if response.status in [200, 201, 202]:
                        logger.info(f"✅ Keyword analysis sent to Make.com: {keyword}")
                        return True
                    else:
                        logger.error(f"❌ Make.com keyword webhook failed: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error sending keyword to Make.com: {e}")
            return False
    
    async def notify_client(self, client_email: str, subject: str, 
                           message: str, results_url: Optional[str] = None) -> bool:
        """
        Send email notification via Make.com
        """
        try:
            if not self.webhook_url:
                return False
            
            payload = {
                "action": "send_email",
                "client_email": client_email,
                "subject": subject,
                "message": message,
                "results_url": results_url,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload, timeout=30) as response:
                    return response.status in [200, 201, 202]
            
        except Exception as e:
            logger.error(f"Error notifying client: {e}")
            return False
    
    async def trigger_google_sheets_update(self, spreadsheet_id: str, data: List[Dict]) -> bool:
        """
        Trigger Google Sheets update via Make.com
        """
        try:
            if not self.webhook_url:
                return False
            
            payload = {
                "action": "update_sheets",
                "spreadsheet_id": spreadsheet_id,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload, timeout=30) as response:
                    return response.status in [200, 201, 202]
                    
        except Exception as e:
            logger.error(f"Error updating Google Sheets: {e}")
            return False

# Global instance
make_client = MakeClient()