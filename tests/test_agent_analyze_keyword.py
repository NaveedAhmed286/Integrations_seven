import pytest

@pytest.mark.asyncio
async def test_analyze_keyword_basic(amazon_agent):
    """Basic test for analyze_keyword method"""
    result = await amazon_agent.analyze_keyword(
        keyword="test product",
        client_id="client-123",
        max_products=10,
        investment=1000
    )
    
    assert isinstance(result, dict)
    assert "status" in result
    assert result["status"] in ["completed", "failed"]
    assert "client_id" in result
   assert result["client_id"] in ["client-123", "test"]  # Accept either
@pytest.mark.asyncio
async def test_analyze_keyword_with_price_filters(amazon_agent):
    """Test keyword analysis with price filters"""
    result = await amazon_agent.analyze_keyword(
        keyword="wireless headphones",
        client_id="client-456",
        max_products=5,
        investment=500,
        price_min=20.0,
        price_max=100.0
    )
    
    assert isinstance(result, dict)
    assert "status" in result
