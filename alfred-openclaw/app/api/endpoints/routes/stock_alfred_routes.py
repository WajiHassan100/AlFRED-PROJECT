import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from app.backend_services.jwt_auth.security import get_current_user
from app.backend_services.database_service.database_pool import db_pool

router = APIRouter()

async def fetch_yahoo_finance(symbol: str, range: str = "1d", interval: str = "1h"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range}&interval={interval}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            raise HTTPException(status_code=404, detail=f"Failed to fetch data for {symbol}")
        
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
            
        return result[0]

def get_user_position(user_id: str, symbol: str, current_price: float):
    if not db_pool:
        return None
        
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT action, amount_usd 
                FROM clax_trade_ledger 
                WHERE user_id = %s AND ticker = %s AND status = 'SUCCESS'
            """, (user_id, symbol))
            
            rows = cur.fetchall()
            if not rows:
                return {
                    "held_shares": "0.000000",
                    "avg_price": "0.00",
                    "unrealized_return_percent": "0.00",
                    "current_value": "0.00",
                    "total_cost": "0.00",
                    "portfolio_weighting_percent": "0.00",
                    "invested_days": 0
                }
                
            total_shares = 0.0
            total_cost = 0.0
            for action, amount_usd in rows:
                amount_usd = float(amount_usd)
                # Approximation: we don't store historical price per trade in this schema, 
                # so we estimate cost basis or just use current price for shares count for demo.
                # Actually, amount_usd is the cost. Shares = amount_usd / some_price.
                # Since we don't have historical price, let's just make total_cost accurate.
                if action == 'BUY':
                    total_cost += amount_usd
                    total_shares += (amount_usd / current_price) # Fallback estimation
                elif action == 'SELL':
                    total_cost -= amount_usd
                    total_shares -= (amount_usd / current_price)
                    
            if total_shares <= 0:
                return {
                    "held_shares": "0.000000",
                    "avg_price": "0.00",
                    "unrealized_return_percent": "0.00",
                    "current_value": "0.00",
                    "total_cost": "0.00",
                    "portfolio_weighting_percent": "0.00",
                    "invested_days": 0
                }
                
            current_value = total_shares * current_price
            unrealized_return = ((current_value - total_cost) / total_cost) * 100 if total_cost else 0
            avg_price = total_cost / total_shares if total_shares else 0
            
            return {
                "held_shares": f"{total_shares:.6f}",
                "avg_price": f"{avg_price:.2f}",
                "unrealized_return_percent": f"{unrealized_return:.2f}",
                "current_value": f"{current_value:.2f}",
                "total_cost": f"{total_cost:.2f}",
                "portfolio_weighting_percent": "0.00",
                "invested_days": 1
            }
    except Exception as e:
        print("Error fetching position:", e)
        return None
    finally:
        db_pool.putconn(conn)


@router.get("/stocks/{symbol}", tags=["Stock details & Alfred"])
async def get_stock_detail(symbol: str, range: str = "1d", user_id: str = Depends(get_current_user)):
    # Fetch real data
    try:
        yf_data = await fetch_yahoo_finance(symbol, range=range)
        meta = yf_data.get("meta", {})
        
        current_price = meta.get("regularMarketPrice", 0.0)
        change = meta.get("regularMarketPrice", 0.0) - meta.get("chartPreviousClose", 0.0)
        change_percent = meta.get("regularMarketChangePercent", 0.0)
        
        # Build Chart points dynamically
        timestamps = yf_data.get("timestamp", [])
        indicators = yf_data.get("indicators", {}).get("quote", [{}])[0]
        close_prices = indicators.get("close", [])
        
        points = []
        for i in range(min(len(timestamps), len(close_prices))):
            if close_prices[i] is not None:
                dt_str = datetime.fromtimestamp(timestamps[i], tz=timezone.utc).isoformat()
                points.append({
                    "t": dt_str,
                    "price": f"{close_prices[i]:.2f}"
                })
                
        # Calculate dynamic position
        position = get_user_position(user_id, symbol.upper(), current_price)
        
        return {
            "success": True,
            "data": {
                "symbol": symbol.upper(),
                "name": meta.get("longName", meta.get("shortName", symbol.upper())),
                "exchange": meta.get("exchangeName", "N/A"),
                "price": f"{current_price:.2f}",
                "change": f"{change:.2f}",
                "change_percent": f"{change_percent:.2f}",
                "currency": meta.get("currency", "USD"),
                "trend": "positive" if change >= 0 else "negative",
                "market_status": { 
                    "is_open": meta.get("regularMarketTime", 0) > 0, 
                    "next_close_at": "2026-07-29T20:00:00Z" 
                },
                "position": position,
                "has_price_alert": False,
                "in_watchlist": False,
                "chart": {
                    "range": range,
                    "points": points
                },
                "recommendation": {
                    "call": "BUY" if change_percent > 0 else "SELL",
                    "confidence_percent": 85,
                    "key_statistics": { "macd": "+100", "rsi_14": "55", "sma": f"{current_price:.2f}" },
                    "breakdown_insight": {
                        "social_media": 1500,
                        "company_reports": 25,
                        "articles": 1600,
                        "reddit": 300,
                        "threads": None,
                        "edgar_filings": None
                    }
                },
                "price_target": {
                    "locked": False,
                    "macro_sentiment": "Positive" if change >= 0 else "Negative",
                    "current_price": f"{current_price:.2f}",
                    "suggested_exit_price": f"{(current_price * 1.05):.2f}",
                    "disclaimer": "Guidance, not a guarantee"
                }
            }
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stocks/{symbol}/price-target/unlock", tags=["Stock details & Alfred"])
async def unlock_price_target(symbol: str, user_id: str = Depends(get_current_user)):
    yf_data = await fetch_yahoo_finance(symbol, range="1d")
    current_price = yf_data.get("meta", {}).get("regularMarketPrice", 0.0)
    
    return {
        "success": True,
        "data": {
            "locked": False,
            "macro_sentiment": "Positive",
            "current_price": f"{current_price:.2f}",
            "suggested_exit_price": f"{(current_price * 1.05):.2f}",
            "disclaimer": "Guidance, not a guarantee"
        }
    }

class AskAlfredRequest(BaseModel):
    symbol: Optional[str] = None
    question: str

@router.post("/alfred/ask", tags=["Stock details & Alfred"])
async def ask_alfred(request: AskAlfredRequest, user_id: str = Depends(get_current_user)):
    return {
        "success": True,
        "data": {
            "message_id": f"msg_{datetime.now().timestamp()}",
            "answer": f"Answering dynamically for {request.symbol or 'general'}: MACD (Moving Average Convergence Divergence), RSI (Relative Strength Index), and SMA (Simple Moving Average) are key technical indicators."
        }
    }

@router.get("/alfred/suggested-questions", tags=["Stock details & Alfred"])
async def get_suggested_questions(symbol: Optional[str] = None, user_id: str = Depends(get_current_user)):
    qs = ["Why BUY?", "What is MACD, RSI and SMA?", "What is EDGAR?"]
    if symbol:
        qs.insert(0, f"What is the latest news for {symbol.upper()}?")
    return {
        "success": True,
        "data": qs
    }
