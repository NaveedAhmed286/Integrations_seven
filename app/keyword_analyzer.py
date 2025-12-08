import os
import json
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional
from app.logger import logger
from app.apify_client import apify_client
from app.agent import agent
from app.memory_manager import memory_manager

class KeywordAnalyzer:
    def __init__(self):
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        
    async def analyze(self, keyword: str, max_products: int = 50) -> Dict:
        """Analyze keyword for Amazon market opportunity"""
        try:
            logger.info(f"Starting keyword analysis: '{keyword}'")
            
            # Step 1: Scrape products for this keyword
            products = await apify_client.scrape_amazon_products(keyword, max_products)
            
            if not products:
                return {
                    "status": "error",
                    "error": "No products found for this keyword",
                    "keyword": keyword
                }
            
            # Step 2: Analyze market data
            market_analysis = await self._analyze_market_data(products, keyword)
            
            # Step 3: Get AI insights
            ai_insights = await self._get_keyword_insights(keyword, products, market_analysis)
            
            # Step 4: Calculate opportunity score
            opportunity_score = self._calculate_opportunity_score(market_analysis, ai_insights)
            
            # Step 5: Generate recommendations
            recommendations = self._generate_recommendations(keyword, market_analysis, ai_insights, opportunity_score)
            
            return {
                "status": "success",
                "keyword": keyword,
                "products_analyzed": len(products),
                "market_analysis": market_analysis,
                "ai_insights": ai_insights,
                "opportunity_score": opportunity_score,
                "recommendations": recommendations,
                "sample_products": products[:3],  # First 3 products as sample
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Keyword analysis error: {e}")
            return {
                "status": "error",
                "keyword": keyword,
                "error": str(e)
            }
    
    async def analyze_with_memory(self, client_id: str, keyword: str, max_products: int = 50) -> Dict:
        """Analyze keyword with client memory context"""
        try:
            # Get client's previous keyword analyses
            client_context = await memory_manager.get_client_context(client_id)
            
            # Perform analysis
            result = await self.analyze(keyword, max_products)
            
            if result["status"] == "success":
                # Store in memory
                task_id = f"keyword_{int(datetime.utcnow().timestamp())}"
                await memory_manager.learn_from_analysis(
                    client_id=client_id,
                    task_id=task_id,
                    analysis_type="keyword_analysis",
                    input_data={"keyword": keyword, "max_products": max_products},
                    result_data=result,
                    key_insights=result.get("ai_insights", {}).get("key_points", [])
                )
                
                result["client_id"] = client_id
                result["personalized"] = True
                
            return result
            
        except Exception as e:
            logger.error(f"Memory keyword analysis error: {e}")
            return await self.analyze(keyword, max_products)  # Fallback
    
    async def _analyze_market_data(self, products: List[Dict], keyword: str) -> Dict:
        """Analyze market data from scraped products"""
        if not products:
            return {}
        
        # Calculate statistics
        prices = [p.get("price") for p in products if p.get("price") and isinstance(p.get("price"), (int, float))]
        ratings = [p.get("rating") for p in products if p.get("rating") and isinstance(p.get("rating"), (int, float))]
        reviews = [p.get("review_count") for p in products if p.get("review_count") and isinstance(p.get("review_count"), int)]
        
        avg_price = sum(prices) / len(prices) if prices else 0
        avg_rating = sum(ratings) / len(ratings) if ratings else 0
        total_reviews = sum(reviews) if reviews else 0
        
        # Competition analysis
        competition_level = self._assess_competition(products)
        
        return {
            "total_products": len(products),
            "average_price": round(avg_price, 2),
            "price_range": {
                "min": min(prices) if prices else 0,
                "max": max(prices) if prices else 0
            },
            "average_rating": round(avg_rating, 2),
            "total_reviews": total_reviews,
            "competition_level": competition_level,
            "market_saturation": self._calculate_saturation(len(products), avg_rating),
            "top_sellers": [p for p in sorted(products, key=lambda x: x.get("review_count", 0), reverse=True)[:3]]
        }
    
    async def _get_keyword_insights(self, keyword: str, products: List[Dict], market_data: Dict) -> Dict:
        """Get AI-powered insights for keyword"""
        if not self.deepseek_api_key:
            return {"key_points": ["AI analysis not configured"]}
        
        try:
            # Prepare context for AI
            context = f"""
            Keyword: {keyword}
            
            Market Analysis:
            - Total Products: {market_data.get('total_products', 0)}
            - Average Price: ${market_data.get('average_price', 0)}
            - Average Rating: {market_data.get('average_rating', 0)}/5
            - Competition Level: {market_data.get('competition_level', 'Unknown')}
            - Market Saturation: {market_data.get('market_saturation', 'Unknown')}
            
            Sample Products (first 3):
            {json.dumps(products[:3], indent=2)}
            
            Provide insights on:
            1. Market opportunity for this keyword
            2. Competitive landscape
            3. Recommended price point
            4. Potential challenges
            5. Success probability
            """
            
            # Call DeepSeek (using agent's method or direct call)
            # This is simplified - integrate with your agent's AI call
            insights = await self._call_deepseek_ai(context)
            
            return {
                "key_points": insights.split("\n") if "\n" in insights else [insights],
                "summary": f"Analysis of '{keyword}' market",
                "generated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"AI insights error: {e}")
            return {"key_points": [f"AI analysis failed: {str(e)}"]}
    
    async def _call_deepseek_ai(self, context: str) -> str:
        """Call DeepSeek API for insights"""
        # Simplified - integrate with your agent's AI calling method
        # For now, return placeholder
        return f"Market analysis for provided context. Consider competition and pricing strategies."
    
    def _assess_competition(self, products: List[Dict]) -> str:
        """Assess competition level"""
        if not products:
            return "Unknown"
        
        avg_rating = sum(p.get("rating", 0) for p in products if p.get("rating")) / len(products)
        total_reviews = sum(p.get("review_count", 0) for p in products if p.get("review_count"))
        
        if len(products) > 100 and total_reviews > 10000:
            return "Very High"
        elif len(products) > 50 and total_reviews > 5000:
            return "High"
        elif len(products) > 20 and total_reviews > 1000:
            return "Medium"
        else:
            return "Low"
    
    def _calculate_saturation(self, product_count: int, avg_rating: float) -> str:
        """Calculate market saturation"""
        if product_count > 100 and avg_rating > 4.0:
            return "Highly Saturated"
        elif product_count > 50 and avg_rating > 3.5:
            return "Saturated"
        elif product_count > 20:
            return "Moderate"
        else:
            return "Low"
    
    def _calculate_opportunity_score(self, market_data: Dict, ai_insights: Dict) -> float:
        """Calculate opportunity score (0-100)"""
        score = 50  # Base score
        
        # Adjust based on competition
        competition = market_data.get("competition_level", "").lower()
        if "low" in competition:
            score += 20
        elif "medium" in competition:
            score += 10
        elif "high" in competition:
            score -= 10
        elif "very high" in competition:
            score -= 20
        
        # Adjust based on market saturation
        saturation = market_data.get("market_saturation", "").lower()
        if "low" in saturation:
            score += 15
        elif "moderate" in saturation:
            score += 5
        elif "saturated" in saturation:
            score -= 10
        
        # Adjust based on average rating
        avg_rating = market_data.get("average_rating", 0)
        if avg_rating > 4.0:
            score += 10
        elif avg_rating > 3.5:
            score += 5
        
        # Ensure score is between 0-100
        return max(0, min(100, round(score, 1)))
    
    def _generate_recommendations(self, keyword: str, market_data: Dict, 
                                 ai_insights: Dict, opportunity_score: float) -> List[str]:
        """Generate actionable recommendations"""
        recommendations = []
        
        if opportunity_score >= 70:
            recommendations.extend([
                f"✅ High opportunity detected for '{keyword}'",
                "Consider entering this market with differentiated products",
                "Focus on quality and customer reviews to stand out",
                "Monitor top competitors for pricing strategies"
            ])
        elif opportunity_score >= 50:
            recommendations.extend([
                f"⚠️ Moderate opportunity for '{keyword}'",
                "Further research recommended before investment",
                "Look for niche sub-categories within this keyword",
                "Consider bundling with related products"
            ])
        else:
            recommendations.extend([
                f"❌ Low opportunity for '{keyword}'",
                "Market is highly competitive or saturated",
                "Consider alternative keywords or products",
                "If proceeding, focus on unique value proposition"
            ])
        
        # Add AI-based recommendations
        key_points = ai_insights.get("key_points", [])
        if key_points and len(key_points) > 0:
            recommendations.append("AI Insights:")
            recommendations.extend(key_points[:2])  # Add top 2 AI insights
        
        return recommendations

# Global instance
keyword_analyzer = KeywordAnalyzer()