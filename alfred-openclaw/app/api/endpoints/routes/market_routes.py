from fastapi import APIRouter, Depends, Query, Header, HTTPException, WebSocket, WebSocketDisconnect
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
import uuid
import asyncio
import json
import random
import httpx
from datetime import datetime, timezone

from app.backend_services.jwt_auth.security import get_current_user
from app.backend_services.database_service.database_pool import db_pool

router = APIRouter()

async def _fetch_home_asset(symbol: str, name: str):
    yf_symbol = symbol
    if symbol == "BTCUSD":
        yf_symbol = "BTC-USD"
    elif symbol == "ETHUSD":
        yf_symbol = "ETH-USD"
    elif symbol == "SOLUSD":
        yf_symbol = "SOL-USD"
        
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol}?range=1d&interval=1h"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                data = resp.json().get("chart", {}).get("result", [])
                if data:
                    meta = data[0].get("meta", {})
                    current_price = meta.get("regularMarketPrice", 0.0)
                    change_percent = meta.get("regularMarketChangePercent", 0.0)
                    timestamps = data[0].get("timestamp", [])
                    close_prices = data[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                    points = []
                    for i in range(min(len(timestamps), len(close_prices))):
                        if close_prices[i] is not None:
                            dt_str = datetime.fromtimestamp(timestamps[i], tz=timezone.utc).isoformat()
                            points.append({"t": dt_str, "price": f"{close_prices[i]:.2f}"})
                    return {
                        "symbol": symbol,
                        "name": meta.get("longName", meta.get("shortName", name)),
                        "price": f"{current_price:.2f}",
                        "change_percent": f"{change_percent:.2f}",
                        "asset_image_url": f"https://api.stock-logos.com/v1/{symbol.lower()}.png",
                        "chart": {"range": "1D", "points": points},
                        "_raw_meta": meta
                    }
    except Exception as e:
        pass
        
    return {
        "symbol": symbol, 
        "name": name, 
        "price": "0.00", 
        "change_percent": "0.00", 
        "asset_image_url": f"https://api.stock-logos.com/v1/{symbol.lower()}.png", 
        "chart": { "range": "1D", "points": [] },
        "_raw_meta": {}
    }



async def _get_category_tickers(category: str, limit: int = 5):
    url_map = {
        "us_stock": "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=most_actives&count=10",
        "hk_stock": "https://query1.finance.yahoo.com/v1/finance/trending/HK",
        "crypto": "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=all_cryptocurrencies_us&count=10"
    }
    if category not in url_map:
        return []
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url_map[category], headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code == 200:
                data = res.json()
                quotes = data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
                tickers = []
                for q in quotes:
                    sym = q.get("symbol")
                    if sym and not sym.startswith('^'):
                        name = q.get("shortName", q.get("longName", sym))
                        tickers.append((sym, name))
                        if len(tickers) >= limit:
                            break
                return tickers
    except:
        pass
    return []


async def _get_market_status():
    exchanges = [
        {"exchange": "NASDAQ", "symbol": "^IXIC"},
        {"exchange": "HKEX", "symbol": "^HSI"},
        {"exchange": "CRYPTO", "symbol": "BTC-USD"}
    ]
    status = []
    async with httpx.AsyncClient() as client:
        for ex in exchanges:
            try:
                res = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ex['symbol']}?range=1d", headers={"User-Agent": "Mozilla/5.0"})
                if res.status_code == 200:
                    meta = res.json().get('chart', {}).get('result', [{}])[0].get('meta', {})
                    periods = meta.get('currentTradingPeriod', {})
                    now = datetime.now(timezone.utc).timestamp()
                    if ex['exchange'] == 'CRYPTO':
                        status.append({"exchange": ex["exchange"], "is_open": True, "next_open_at": None, "next_close_at": None})
                    else:
                        reg = periods.get('regular', {})
                        start = reg.get('start', 0)
                        end = reg.get('end', 0)
                        is_open = start <= now <= end
                        next_open = datetime.fromtimestamp(start, tz=timezone.utc).isoformat() if start else None
                        next_close = datetime.fromtimestamp(end, tz=timezone.utc).isoformat() if end else None
                        status.append({"exchange": ex["exchange"], "is_open": is_open, "next_open_at": next_open, "next_close_at": next_close})
                else:
                    status.append({"exchange": ex["exchange"], "is_open": False, "next_open_at": None, "next_close_at": None})
            except:
                status.append({"exchange": ex["exchange"], "is_open": False, "next_open_at": None, "next_close_at": None})
    return status

async def _search_yahoo(q: str):
    if not q: return []
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={q}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                quotes = resp.json().get("quotes", [])
                results = []
                for item in quotes:
                    results.append({
                        "symbol": item.get("symbol", ""),
                        "name": item.get("shortname", item.get("longname", "")),
                        "asset_class": item.get("quoteType", "UNKNOWN")
                    })
                return results
    except:
        pass
    return []

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
            if not rows: return None
            total_shares = 0.0
            total_cost = 0.0
            for action, amount_usd in rows:
                amount_usd = float(amount_usd)
                if action == 'BUY':
                    total_cost += amount_usd
                    total_shares += (amount_usd / current_price) if current_price else 0
                elif action == 'SELL':
                    total_cost -= amount_usd
                    total_shares -= (amount_usd / current_price) if current_price else 0
            if total_shares <= 0: return None
            current_value = total_shares * current_price
            unrealized_return = ((current_value - total_cost) / total_cost) * 100 if total_cost else 0
            avg_price = total_cost / total_shares if total_shares else 0
            return {
                "total_shares_held": round(total_shares, 6),
                "avg_price": round(avg_price, 2),
                "pnl_percentage": round(unrealized_return, 2),
                "current_value": round(current_value, 2),
                "total_cost": round(total_cost, 2),
                "unrealized_return": { "absolute": round(current_value - total_cost, 2), "percentage": round(unrealized_return, 2) },
                "quantity": round(total_shares, 6),
                "current_price": current_price,
                "avg_cost_basis": round(avg_price, 2),
                "avg_cost_paid": round(avg_price, 2),
                "portfolio_weight_pct": 0,
                "invested_since": datetime.utcnow().strftime("%Y-%m-%d"),
                "invested_days": 1
            }
    except Exception as e:
        return None
    finally:
        db_pool.putconn(conn)


@router.get("/home")
async def get_home(
    q: Optional[str] = Query(None, description="Search query"),
    category: Optional[str] = Query(None, description="Optional category filter for search/movers"),
    limit: int = Query(5, description="Number of items to return for movers"),
    ticker: Optional[str] = Query(None, description="Specific ticker for stock details"),
    user_id: str = Depends(get_current_user)
):
    greeting_name = "User"
    wallet_balance = "0.00"
    if db_pool:
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT full_name, portfolio_value FROM clax_users WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                if row:
                    greeting_name = row[0].split()[0] if row[0] else "User"
                    wallet_balance = f"{row[1]:.2f}" if row[1] is not None else "0.00"
        except Exception:
            pass
        finally:
            db_pool.putconn(conn)
            
    
    # Dynamically fetch top assets for each category
    us_tickers = await _get_category_tickers("us_stock", 5)
    hk_tickers = await _get_category_tickers("hk_stock", 1)
    crypto_tickers = await _get_category_tickers("crypto", 1)

    tasks = []
    # 1. Home tasks
    for sym, name in us_tickers + hk_tickers + crypto_tickers:
        tasks.append(_fetch_home_asset(sym, name))
    
    # 2. Movers tasks
    movers_tickers = []
    if category:
        movers_tickers = await _get_category_tickers(category, limit)
        for sym, name in movers_tickers:
            tasks.append(_fetch_home_asset(sym, name))
            
    # 3. Ticker task
    if ticker:
        tasks.append(_fetch_home_asset(ticker.upper(), ticker.upper()))

    all_results = await asyncio.gather(*tasks)
    
    us_count = len(us_tickers)
    hk_count = len(hk_tickers)
    crypto_count = len(crypto_tickers)
    
    us_home = [r.copy() for r in all_results[0:us_count]]
    hk_home = [r.copy() for r in all_results[us_count:us_count+hk_count]]
    crypto_home = [r.copy() for r in all_results[us_count+hk_count:us_count+hk_count+crypto_count]]
    
    for r in us_home + hk_home + crypto_home:
        r.pop("_raw_meta", None)
        
    home_data = {
        "greeting_name": greeting_name,
        "wallet_quick_balance": wallet_balance,
        "categories": {
            "us_stock": us_home,
            "hk_stock": hk_home,
            "crypto": crypto_home
        },
        "assistant_prompt": "Tap me anytime to talk."
    }

    movers = []
    idx = us_count + hk_count + crypto_count
    if category and movers_tickers:
        movers_count = len(movers_tickers)
        fetched_movers = all_results[idx:idx+movers_count]
        idx += movers_count
        fetched_movers.sort(key=lambda x: float(x["change_percent"]), reverse=True)
        for m in fetched_movers[:limit]:
            mc = m.copy()
            mc.pop("_raw_meta", None)
            mc.pop("chart", None)
            movers.append(mc)
            
    stock_details = None
    if ticker:
        ticker_res = all_results[idx]
        current_price = float(ticker_res["price"])
        change_abs = (float(ticker_res["change_percent"]) / 100.0) * current_price if current_price else 0.0
        
        stock_details = {
            "ticker": ticker_res["symbol"],
            "name": ticker_res["name"],
            "asset_image_url": ticker_res["asset_image_url"],
            "quote": {
                "current_price": current_price,
                "price_change": { "absolute": round(change_abs, 2), "percentage": float(ticker_res["change_percent"]) },
                "market_status": "open",
                "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            },
            "statistics": { "macd": 240, "rsi_14": 38.6, "sma": current_price },
            "indicator": { "signal": "buy" if float(ticker_res["change_percent"]) > 0 else "sell", "confidence": 0.90, "suggestion": "Trending" },
            "macro_sentiment": { "value": 0.76, "label": "positive" if float(ticker_res["change_percent"]) > 0 else "negative" },
            "holding": get_user_position(user_id, ticker_res["symbol"], current_price) or {
                "total_shares_held": 0, "avg_price": 0, "pnl_percentage": 0, "current_value": 0,
                "total_cost": 0, "unrealized_return": { "absolute": 0, "percentage": 0 },
                "quantity": 0, "current_price": current_price, "avg_cost_basis": 0, "avg_cost_paid": 0,
                "portfolio_weight_pct": 0, "invested_since": "-", "invested_days": 0
            }
        }

    search_results = await _search_yahoo(q)

    market_status = await _get_market_status()

    return {
        "success": True,
        "data": {
            "home": home_data,
            "movers": movers,
            "search": search_results,
            "status": market_status,
            "stock_details": stock_details
        }
    }


# WebSockets
@router.websocket("/ws/v1/quotes")
async def websocket_quotes(websocket: WebSocket):
    await websocket.accept()
    active_tickers = set()
    
    try:
        while True:
            receive_task = asyncio.create_task(websocket.receive_text())
            push_task = asyncio.create_task(asyncio.sleep(3))
            
            done, pending = await asyncio.wait(
                [receive_task, push_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            if receive_task in done:
                data = receive_task.result()
                try:
                    msg = json.loads(data)
                    action = msg.get("action")
                    tickers = msg.get("tickers", [])
                    if action == "subscribe":
                        active_tickers.update(tickers)
                    elif action == "unsubscribe":
                        for t in tickers:
                            active_tickers.discard(t)
                except json.JSONDecodeError:
                    pass
                
            if push_task in done:
                tickers_to_fetch = list(active_tickers)[:5]
                if tickers_to_fetch:
                    async with httpx.AsyncClient() as client:
                        for ticker in tickers_to_fetch:
                            try:
                                res = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1m", headers={"User-Agent": "Mozilla/5.0"})
                                if res.status_code == 200:
                                    meta = res.json().get('chart', {}).get('result', [{}])[0].get('meta', {})
                                    price = meta.get('regularMarketPrice')
                                    prev_close = meta.get('chartPreviousClose')
                                    if price and prev_close:
                                        abs_change = price - prev_close
                                        pct_change = (abs_change / prev_close) * 100
                                        update = {
                                            "ticker": ticker,
                                            "quote": {
                                                "current_price": round(price, 2),
                                                "price_change": {
                                                    "absolute": round(abs_change, 2),
                                                    "percentage": round(pct_change, 2)
                                                },
                                                "market_status": "open",
                                                "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                                            }
                                        }
                                        await websocket.send_json(update)
                            except Exception as e:
                                pass
                    
            for task in pending:
                task.cancel()
                
    except WebSocketDisconnect:
        pass

