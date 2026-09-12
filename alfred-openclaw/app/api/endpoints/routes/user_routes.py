from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, constr
from typing import Optional

from app.backend_services.jwt_auth.security import get_current_user
from app.backend_services.database_service.database_pool import db_pool

user_router = APIRouter()

class UpdateProfileRequest(BaseModel):
    full_name: Optional[constr(min_length=1, max_length=100)] = None
    currency: Optional[constr(min_length=3, max_length=3)] = None
    email: Optional[str] = None
    investor_archetype: Optional[str] = None

currency_map = {
    "USD": "US Dollar",
    "HKD": "Hong Kong Dollar",
    "EUR": "Euro",
    "GBP": "British Pound",
    "SGD": "Singapore Dollar"
}

def _init_db():
    if db_pool:
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS clax_users (
                        user_id VARCHAR(255) PRIMARY KEY,
                        email VARCHAR(255),
                        full_name VARCHAR(255),
                        investor_archetype VARCHAR(255),
                        member_since TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        default_currency VARCHAR(10) DEFAULT 'USD',
                        portfolio_value DECIMAL(18,2) DEFAULT 0.00,
                        portfolio_today_change_percent DECIMAL(5,2) DEFAULT 0.00
                    )
                """)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("DB init error:", e)
        finally:
            db_pool.putconn(conn)

_init_db()

@user_router.get("/users/me", tags=["Profile & settings"])
async def get_current_user_profile(user_id: str = Depends(get_current_user)):
    if not db_pool:
        # Fallback to in-memory if no DB is available
        return {"success": True, "data": {"id": user_id, "error": "Database not configured"}}
        
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM clax_users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                cur.execute("""
                    INSERT INTO clax_users (user_id, email, full_name, investor_archetype, default_currency, portfolio_value, portfolio_today_change_percent)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (user_id, f"{user_id}@company.com", "John Doe", "Ambitious Builder", "USD", 65000.00, 4.2))
                row = cur.fetchone()
                conn.commit()
            
            colnames = [desc[0] for desc in cur.description]
            user_data = dict(zip(colnames, row))
            if 'member_since' in user_data and user_data['member_since']:
                user_data['member_since'] = user_data['member_since'].strftime("%Y-%m-%d")
            if 'portfolio_value' in user_data:
                user_data['portfolio_value'] = str(user_data['portfolio_value'])
            if 'portfolio_today_change_percent' in user_data:
                user_data['portfolio_today_change_percent'] = str(user_data['portfolio_today_change_percent'])
            user_data['id'] = user_data['user_id']
            
            return {
                "success": True,
                "data": user_data
            }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db_pool.putconn(conn)


@user_router.patch("/users/me", tags=["Profile & settings"])
async def update_profile(request: UpdateProfileRequest, user_id: str = Depends(get_current_user)):
    if not db_pool:
        raise HTTPException(status_code=500, detail="Database not configured")
        
    if request.currency is not None:
        currency = request.currency.upper()
        if currency not in currency_map:
            raise HTTPException(status_code=422, detail="Unsupported currency code")
        request.currency = currency
        
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM clax_users WHERE user_id = %s", (user_id,))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO clax_users (user_id, email, full_name, investor_archetype, default_currency, portfolio_value, portfolio_today_change_percent)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (user_id, f"{user_id}@company.com", "John Doe", "Ambitious Builder", "USD", 65000.00, 4.2))
            
            updates = []
            params = []
            if request.full_name is not None:
                updates.append("full_name = %s")
                params.append(request.full_name)
            if request.email is not None:
                updates.append("email = %s")
                params.append(request.email)
            if request.investor_archetype is not None:
                updates.append("investor_archetype = %s")
                params.append(request.investor_archetype)
            if request.currency is not None:
                updates.append("default_currency = %s")
                params.append(request.currency)
                
            if updates:
                query = f"UPDATE clax_users SET {', '.join(updates)} WHERE user_id = %s RETURNING *"
                params.append(user_id)
                cur.execute(query, tuple(params))
                row = cur.fetchone()
            else:
                cur.execute("SELECT * FROM clax_users WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                
            conn.commit()
            colnames = [desc[0] for desc in cur.description]
            user_data = dict(zip(colnames, row))
            
            if 'member_since' in user_data and user_data['member_since']:
                user_data['member_since'] = user_data['member_since'].strftime("%Y-%m-%d")
            if 'portfolio_value' in user_data:
                user_data['portfolio_value'] = str(user_data['portfolio_value'])
            if 'portfolio_today_change_percent' in user_data:
                user_data['portfolio_today_change_percent'] = str(user_data['portfolio_today_change_percent'])
            user_data['id'] = user_data['user_id']
            
            return {
                "success": True,
                "data": user_data
            }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db_pool.putconn(conn)


@user_router.delete("/users/me", tags=["Profile & settings"])
async def delete_account(user_id: str = Depends(get_current_user)):
    if not db_pool:
        raise HTTPException(status_code=500, detail="Database not configured")
        
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM clax_users WHERE user_id = %s", (user_id,))
            conn.commit()
            return {
                "success": True,
                "data": { "status": "deletion_scheduled" }
            }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db_pool.putconn(conn)
