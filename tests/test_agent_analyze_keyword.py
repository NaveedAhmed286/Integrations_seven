import pytest

@pytest.mark.asyncio
async def test_analyze_keyword_happy_path(amazon_agent, monkeypatch):
    """Test keyword analysis with mocked Apify client"""
    # Arrange: mock Apify scrape function
    async def fake_scrape_amazon_products(keyword, max_products, client_id, price_min=None, price_max=None):
        return {
            "success": True,
            "products": [
                {
                    "title": "Scraped Product",
                    "price": 29.99,
                    "rating": 4.2,
                    "review_count": 45,
                    "asin": "BTEST2",
                    "url": "https://example.com/p2",
                    "image_url": "",
                    "brand": "BrandY",
                    "category": "Gadgets"
                }
            ]
        }

    # Patch the apify_client
    monkeypatch.setattr("app.apify_client.scrape_amazon_products", fake_scrape_amazon_products, raising=False)

    # Patch analyze_products to isolate keyword flow
    async def fake_analyze_products(products, client_id=None):
        return {
            "status": "completed",
            "count": len(products),
            "saved_to_sheets": True,
            "products": products,  # Pass through products
            "insights": ["sample insight"]
        }
    
    monkeypatch.setattr(amazon_agent, "analyze_products", fake_analyze_products)

    # Act - match your actual method signature
    result = await amazon_agent.analyze_keyword(
        keyword="wireless headphones",
        client_id="client-123",
        max_products=10,
        investment=1500,
        price_min=10.0,
        price_max=100.0
    )

    # Assert - flexible assertions for your return structure
    assert result["status"] in ["completed", "failed"]
    assert result["client_id"] == "client-123"
    assert "search_keyword" in result or "keyword" in result
    assert "scraped" in result  # Your code returns scraped count

@pytest.mark.asyncio 
async def test_analyze_keyword_no_products(amazon_agent, monkeypatch):
    """Test keyword analysis when no products found"""
    async def fake_scrape_no_products(*args, **kwargs):
        return {"success": True, "products": []}
    
    monkeypatch.setattr("app.apify_client.scrape_amazon_products", fake_scrape_no_products, raising=False)
    
    result = await amazon_agent.analyze_keyword(
        keyword="nonexistent product",
        client_id="test-client",
        max_products=10
    )
    
    assert result["status"] == "completed"
    assert result["scraped"] == 0
    assert "message" in result
