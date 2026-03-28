from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from collections import defaultdict
import uvicorn

import config
import database
import models
import utils
from web_socket import web_socket

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

templates = Jinja2Templates(directory="templates")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

calories_tracker = defaultdict(float)
last_update_time = {}

database.init_db()

async def verify_api_key(header_value: str = Depends(api_key_header)):
    if header_value != config.API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return header_value

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await web_socket.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        web_socket.disconnect(websocket)

@app.get("/", response_class=HTMLResponse)
async def read_dashboard(request: Request):
    rows = database.get_dashboard_data()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "data": rows,
        "now": datetime.now().strftime("%H:%M:%S"),
        "tracking_timeout_sec": database.get_tracking_timeout_sec()
    })


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/dashboard/users")
async def dashboard_users():
    rows = database.get_users_for_rental()
    return [
        {
            "id": row["id"],
            "first_name": row["first_name"],
            "last_name": row["last_name"]
        }
        for row in rows
    ]

@app.get("/dashboard/users/full")
async def dashboard_users_full():
    rows = database.get_users_full()
    return [
        {
            "id": row["id"],
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "middle_name": row["middle_name"],
            "age": row["age"],
            "height": row["height"],
            "weight": row["weight"],
            "sex": row["sex"]
        }
        for row in rows
    ]

@app.get("/dashboard/trackers")
async def dashboard_trackers():
    rows = database.get_trackers_for_rental()
    return [
        {
            "device_id": row["device_id"],
            "name": row["name"],
            "correction_factor": row["correction_factor"]
        }
        for row in rows
    ]

@app.get("/dashboard/rentals/status")
async def dashboard_rental_status(customer_id: int, device_id: int):
    is_active = database.is_pair_rental_active(customer_id, device_id)
    return {"active": is_active}

@app.get("/dashboard/rentals/active-customer")
async def dashboard_active_customer(device_id: int):
    active = database.get_active_customer_for_device(device_id)
    if not active:
        return {"active_customer_id": None}
    return {"active_customer_id": active["customer_id"]}

@app.put("/dashboard/trackers/{device_id}/name")
async def dashboard_update_tracker_name(device_id: int, payload: models.TrackerNameUpdate):
    success = database.update_tracker_name(device_id, payload.name)
    if not success:
        raise HTTPException(status_code=404, detail="Tracker not found or invalid name")
    return {"status": "ok", "device_id": device_id, "name": payload.name}

@app.put("/dashboard/trackers/{device_id}")
async def dashboard_update_tracker(device_id: int, payload: models.TrackerUpdate):
    success = database.update_tracker_settings(device_id, payload.name, payload.correction_factor)
    if not success:
        raise HTTPException(status_code=404, detail="Tracker not found or invalid payload")
    return {
        "status": "ok",
        "device_id": device_id,
        "name": payload.name,
        "correction_factor": payload.correction_factor
    }

@app.post("/dashboard/users")
async def dashboard_create_user(user: models.UserCreate):
    with database.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (first_name, last_name, middle_name, age, height, weight, sex)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user.first_name, user.last_name, user.middle_name, user.age, user.height, user.weight, user.sex))
        return {"status": "success", "user_id": cursor.lastrowid}

@app.put("/dashboard/users/{user_id}")
async def dashboard_update_user(user_id: int, payload: models.UserUpdate):
    update_data = payload.dict(exclude_unset=True)
    success = database.update_user(user_id, update_data)
    if not success:
        raise HTTPException(status_code=404, detail="User not found or no fields updated")
    return {"status": "ok", "user_id": user_id}

@app.get("/dashboard/settings/search-new-trackers")
async def dashboard_get_search_new_trackers():
    return {"enabled": database.is_search_new_trackers_enabled()}

@app.post("/dashboard/settings/search-new-trackers/toggle")
async def dashboard_toggle_search_new_trackers():
    new_value = not database.is_search_new_trackers_enabled()
    database.set_search_new_trackers_enabled(new_value)
    return {"status": "ok", "enabled": new_value}

@app.post("/dashboard/rentals/start")
async def dashboard_start_rental(rental: models.RentalCreate):
    try:
        result = database.start_or_resume_rental(rental.customer_id, rental.device_id)
        calories_tracker[rental.device_id] = float(result["calories"] or 0.0)
        return {
            "status": "started",
            "action": result["action"],
            "device_id": rental.device_id,
            "customer_id": rental.customer_id
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

@app.get("/dashboard/history")
async def dashboard_history(
    device_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    filter_date: Optional[str] = None,
    sort_by: str = "day",
    sort_dir: str = "desc",
    limit: int = Query(500, le=2000, ge=1),
    offset: int = Query(0, ge=0),
):
    allowed_sort = {"day", "device_name", "customer_fullname", "training_seconds", "calories"}
    if sort_by not in allowed_sort:
        sort_by = "day"
    rows = database.get_daily_training_history(
        device_id=device_id,
        customer_id=customer_id,
        filter_date=filter_date,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )
    return {"rows": rows}

@app.post("/dashboard/rentals/stop")
async def dashboard_stop_rental(customer_id: int, device_id: int):
    updated_rows = database.stop_pair_rental(customer_id, device_id)
    if updated_rows > 0:
        await web_socket.broadcast({
            "event": "rental_stopped",
            "device_id": device_id,
            "customer_id": customer_id
        })
    return {"status": "finished", "updated_rows": updated_rows, "device_id": device_id, "customer_id": customer_id}

@app.get("/settings/search-new-trackers")
async def get_search_new_trackers(api_key: str = Depends(verify_api_key)):
    return {"enabled": database.is_search_new_trackers_enabled()}

@app.put("/settings/search-new-trackers")
async def set_search_new_trackers(
    payload: models.SearchNewTrackersUpdate,
    api_key: str = Depends(verify_api_key)
):
    database.set_search_new_trackers_enabled(payload.enabled)
    return {"status": "ok", "enabled": payload.enabled}

@app.post("/log")
async def log_heart_rate(request: Request, api_key: str = Depends(verify_api_key)):
    try:
        data = await request.json()
        d_id, hr, ts = data['d_id'], data['hr'], data['ts']

        if database.is_search_new_trackers_enabled():
            database.add_tracker_if_missing(d_id)

        with database.get_db_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO heart_rates (device_id, timestamp, hr) VALUES (?, ?, ?)", (d_id, ts, hr))

        user = database.get_active_user(d_id)
        if user:
            correction_factor = database.get_tracker_correction_factor(d_id)
            hr_corrected = int(round(float(hr) * correction_factor))

            if d_id not in calories_tracker or calories_tracker[d_id] == 0:
                calories_tracker[d_id] = float(user['calories'] or 0.0)

            now = datetime.now()
            start_dt = datetime.fromisoformat(user['start_at'])
            fitness_time = str(now - start_dt).split('.')[0]

            if d_id in last_update_time:
                delta = (now - last_update_time[d_id]).total_seconds()
                if 0 < delta < 10:
                    # ПЕРЕДАЄМО SEX
                    kcal_gain = utils.calculate_calories(hr, user['age'], user['weight'], user['sex'], delta)
                    calories_tracker[d_id] += kcal_gain
                    database.update_rental_calories(d_id, round(calories_tracker[d_id], 2))

            last_update_time[d_id] = now

            await web_socket.broadcast({
                "device_id": d_id,
                "first_name": user['first_name'],
                "last_name": user['last_name'],
                "fitness_time": fitness_time,
                "hr": hr_corrected,
                "calories": round(calories_tracker[d_id], 1),
                "ts": ts
            })

        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/users/register")
async def register(user: models.UserCreate, api_key: str = Depends(verify_api_key)):
    try:
        with database.get_db_connection() as conn:
            cursor = conn.cursor()
            # ДОДАНО POLE sex У ЗАПИТ
            cursor.execute("""
                INSERT INTO users (first_name, last_name, middle_name, age, height, weight, sex)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user.first_name, user.last_name, user.middle_name, user.age, user.height, user.weight, user.sex))
            return {"status": "success", "user_id": cursor.lastrowid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/users/{user_id}")
async def edit_user(user_id: int, user_data: models.UserUpdate, api_key: str = Depends(verify_api_key)):
    try:
        # Перетворюємо модель Pydantic у словник
        update_data = user_data.dict(exclude_unset=True)

        success = database.update_user(user_id, update_data)

        if success:
            return {"status": "success", "message": f"Користувача {user_id} оновлено"}
        else:
            raise HTTPException(status_code=404, detail="Користувача не знайдено")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/users/{user_id}")
async def delete_user(user_id: int, api_key: str = Depends(verify_api_key)):
    try:
        success = database.delete_user_full(user_id)
        if success:
            return {"status": "success", "message": f"Користувача {user_id} та всі його дані видалено"}
        else:
            raise HTTPException(status_code=404, detail="Користувача не знайдено")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rentals/start")
async def start_rental(rental: models.RentalCreate, api_key: str = Depends(verify_api_key)):
    try:
        result = database.start_or_resume_rental(rental.customer_id, rental.device_id)
        calories_tracker[rental.device_id] = float(result["calories"] or 0.0)
        return {"status": "started", "action": result["action"], "device_id": rental.device_id}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rentals/stop")
async def stop_rental(device_id: int, api_key: str = Depends(verify_api_key)):
    try:
        now_str = datetime.now().isoformat()
        with database.get_db_connection() as conn:
            cursor = conn.execute("UPDATE device_rentals SET finish_at = ? WHERE device_id = ? AND finish_at IS NULL",
                                  (now_str, device_id))
        if cursor.rowcount > 0:
            await web_socket.broadcast({
                "event": "rental_stopped",
                "device_id": device_id
            })
        return {"status": "finished", "device_id": device_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.PORT)