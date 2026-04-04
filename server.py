import asyncio
import base64
import secrets
import os
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def _admin_basic_unauthorized():
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="SmartFizruk Admin"'},
    )


def _admin_not_configured():
    return Response(
        status_code=403,
        content="Адмін-зона недоступна: задайте ADMIN_USERNAME та ADMIN_PASSWORD у .env на сервері.",
        media_type="text/plain; charset=utf-8",
    )


@app.middleware("http")
async def admin_area_auth(request: Request, call_next):
    """Захист /admin та /dashboard/*: без повних облікових у .env — 403; інакше HTTP Basic.
    Головний дашборд / (картки) та /ws — без пароля."""
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    # Головний TV-дашборд і live-канал не закриваємо (не плутати з API /dashboard/* для адмінки).
    if path == "/" or path == "/ws":
        return await call_next(request)
    if path != "/admin" and not path.startswith("/dashboard"):
        return await call_next(request)
    # Адмін-зона: без обох змінних у .env — зовсім без доступу (не «відкрито для розробки»).
    if not config.ADMIN_AUTH_ENABLED:
        return _admin_not_configured()
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Basic "):
        return _admin_basic_unauthorized()
    try:
        raw = base64.b64decode(auth[6:].strip()).decode("utf-8")
        if ":" not in raw:
            return _admin_basic_unauthorized()
        username, password = raw.split(":", 1)
    except Exception:
        return _admin_basic_unauthorized()
    ok = secrets.compare_digest(username, config.ADMIN_USERNAME) and secrets.compare_digest(
        password, config.ADMIN_PASSWORD
    )
    if not ok:
        return _admin_basic_unauthorized()
    return await call_next(request)


templates = Jinja2Templates(directory="templates")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

calories_tracker = defaultdict(float)
last_update_time = {}
# Пристрої, для яких уже відправили WS «пульс 0 + актуальні ккал» при відсутності свіжого пульсу (щоб не спамити).
stale_ws_sent: set = set()

database.init_db()


def _rental_fitness_time_str(start_at_raw) -> str:
    try:
        s = str(start_at_raw).strip()
        if " " in s and "T" not in s[:11]:
            s = s.replace(" ", "T", 1)
        start_dt = datetime.fromisoformat(s)
        return str(datetime.now() - start_dt).split(".")[0]
    except Exception:
        return "0:00:00"


def _display_calories_for_rented_device(device_id: int) -> float:
    """Ккал для UI: in-memory після /log, інакше з активної оренди в БД."""
    user = database.get_active_user(device_id)
    if not user:
        return 0.0
    if device_id in calories_tracker:
        return float(calories_tracker[device_id])
    return float(user["calories"] or 0.0)


async def _broadcast_rental_live_ui(device_id: int, hr: int, calories: float):
    user = database.get_active_user(device_id)
    if not user:
        return
    await web_socket.broadcast({
        "device_id": device_id,
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "start_at": user["start_at"],
        "fitness_time": _rental_fitness_time_str(user["start_at"]),
        "hr": int(hr),
        "calories": round(float(calories), 1),
    })


async def _dashboard_stale_watch_loop():
    while True:
        await asyncio.sleep(1)
        try:
            timeout = database.get_tracking_timeout_sec()
            now = datetime.now()
            for row in database.get_active_rentals_for_stale_tick():
                d_id = int(row["device_id"])
                last = last_update_time.get(d_id)
                fresh = last is not None and (now - last).total_seconds() <= float(timeout)
                if fresh:
                    stale_ws_sent.discard(d_id)
                    continue
                if d_id in stale_ws_sent:
                    continue
                kcal = _display_calories_for_rented_device(d_id)
                await _broadcast_rental_live_ui(d_id, 0, kcal)
                stale_ws_sent.add(d_id)
        except Exception:
            pass


@app.on_event("startup")
async def _start_dashboard_stale_watcher():
    asyncio.create_task(_dashboard_stale_watch_loop())


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
    calories_offset_raw = request.query_params.get("calories_offset")
    heartrate_offset_raw = request.query_params.get("heartrate_offset")
    try:
        calories_offset = float(calories_offset_raw) if calories_offset_raw is not None else 0.0
    except (TypeError, ValueError):
        calories_offset = 0.0
    try:
        heartrate_offset = float(heartrate_offset_raw) if heartrate_offset_raw is not None else 0.0
    except (TypeError, ValueError):
        heartrate_offset = 0.0

    timeout = database.get_tracking_timeout_sec()
    now = datetime.now()
    rows = []
    for row in database.get_dashboard_data():
        item = dict(row)
        database.apply_dashboard_stale_display(item, timeout, now)
        item["calories"] = float(item.get("calories") or 0.0) + calories_offset
        if item.get("hr") is not None:
            item["hr"] = int(round(float(item["hr"]) + heartrate_offset))
        rows.append(item)

    test_count_raw = request.query_params.get("test_count")
    if test_count_raw:
        try:
            test_count = int(test_count_raw)
        except (TypeError, ValueError):
            test_count = None

        if test_count and test_count > 0 and rows:
            source = [dict(row) for row in rows]
            rows = [dict(source[i % len(source)]) for i in range(test_count)]

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


@app.get("/dashboard/rentals/active-count")
async def dashboard_active_pairs_count():
    return {"active_pairs": database.get_active_pairs_count()}

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
        if result["action"] != "already_active":
            last_update_time.pop(rental.device_id, None)
            start_kcal = float(result["calories"] or 0.0)
            await _broadcast_rental_live_ui(rental.device_id, 0, start_kcal)
            stale_ws_sent.add(rental.device_id)
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
        last_update_time.pop(device_id, None)
        calories_tracker.pop(device_id, None)
        stale_ws_sent.discard(device_id)
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
        d_id = int(d_id)

        if database.is_search_new_trackers_enabled():
            database.add_tracker_if_missing(d_id)

        with database.get_db_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO heart_rates (device_id, timestamp, hr) VALUES (?, ?, ?)", (d_id, ts, hr))

        user = database.get_active_user(d_id)
        if user:
            correction_factor = database.get_tracker_correction_factor(d_id)
            hr_corrected = int(round(float(hr) * correction_factor))

            # Лише перший раз підтягуємо з БД; перевірка == 0 знімала накопичення й разом з round() тримала ккал на 0
            if d_id not in calories_tracker:
                calories_tracker[d_id] = float(user['calories'] or 0.0)

            now = datetime.now()
            start_dt = datetime.fromisoformat(user['start_at'])
            fitness_time = str(now - start_dt).split('.')[0]

            if d_id in last_update_time:
                delta = (now - last_update_time[d_id]).total_seconds()
                # Раніше було 0 < delta < 10: тоді рідкі пакети (>10 с) майже не давали ккал порівняно з частими.
                # Рахуємо за повним інтервалом; довгі паузи (офлайн) обрізаємо, щоб один пакет не «донарахував» хвилини.
                if 0 < delta <= 120:
                    effective_delta = min(delta, 30.0)
                    kcal_gain = utils.calculate_calories(
                        hr_corrected, user['age'], user['weight'], user['sex'], effective_delta
                    )
                    calories_tracker[d_id] += kcal_gain
                    database.update_rental_calories(d_id, round(calories_tracker[d_id], 1))

            last_update_time[d_id] = now
            stale_ws_sent.discard(d_id)

            await web_socket.broadcast({
                "device_id": d_id,
                "first_name": user['first_name'],
                "last_name": user['last_name'],
                "start_at": user['start_at'],
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
        if result["action"] != "already_active":
            last_update_time.pop(rental.device_id, None)
            start_kcal = float(result["calories"] or 0.0)
            await _broadcast_rental_live_ui(rental.device_id, 0, start_kcal)
            stale_ws_sent.add(rental.device_id)
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
            last_update_time.pop(device_id, None)
            calories_tracker.pop(device_id, None)
            stale_ws_sent.discard(device_id)
            await web_socket.broadcast({
                "event": "rental_stopped",
                "device_id": device_id
            })
        return {"status": "finished", "device_id": device_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.PORT)