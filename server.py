import os
import sqlite3
import base64
import json
from datetime import datetime, date
from flask import Flask, request, jsonify, send_from_directory

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
except ImportError:
    pass

app = Flask(__name__, static_folder='public', static_url_path='')

DATABASE_URL = os.environ.get('DATABASE_URL', '')
USE_PG = bool(DATABASE_URL)
DB_PATH = os.path.join(os.path.dirname(__file__), 'nutrition.db')

# ─── DB abstraction ───────────────────────────────────────────────────────────

if USE_PG:
    import psycopg2
    import psycopg2.extras
    PH = '%s'

    def get_db():
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn

    def q(conn, sql, params=()):
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return cur

    def fetchall(cur): return [dict(r) for r in cur.fetchall()]
    def fetchone(cur):
        r = cur.fetchone(); return dict(r) if r else None
    def lastid(cur):
        cur.execute('SELECT lastval()')
        row = cur.fetchone()
        return row['lastval'] if hasattr(row, 'keys') else row[0]
else:
    PH = '?'

    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def q(conn, sql, params=()):
        return conn.execute(sql, params)

    def fetchall(cur): return [dict(r) for r in cur.fetchall()]
    def fetchone(cur):
        r = cur.fetchone(); return dict(r) if r else None
    def lastid(cur): return cur.lastrowid

def init_db():
    conn = get_db()
    try:
        if USE_PG:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS profile (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    name TEXT DEFAULT 'Me',
                    current_weight REAL,
                    target_weight REAL,
                    daily_calories INTEGER DEFAULT 2000,
                    daily_protein INTEGER DEFAULT 150,
                    daily_carbs INTEGER DEFAULT 200,
                    daily_fat INTEGER DEFAULT 65
                );
                CREATE TABLE IF NOT EXISTS meal_logs (
                    id SERIAL PRIMARY KEY,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    meal_name TEXT NOT NULL,
                    calories REAL DEFAULT 0,
                    protein REAL DEFAULT 0,
                    carbs REAL DEFAULT 0,
                    fat REAL DEFAULT 0,
                    photo_used INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS workout_logs (
                    id SERIAL PRIMARY KEY,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    activity TEXT NOT NULL,
                    duration_min INTEGER DEFAULT 0,
                    calories_burned REAL DEFAULT 0,
                    notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS weight_logs (
                    id SERIAL PRIMARY KEY,
                    date TEXT NOT NULL,
                    weight REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS favorite_meals (
                    id SERIAL PRIMARY KEY,
                    meal_name TEXT NOT NULL,
                    calories REAL DEFAULT 0,
                    protein REAL DEFAULT 0,
                    carbs REAL DEFAULT 0,
                    fat REAL DEFAULT 0,
                    times_used INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
        else:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    name TEXT DEFAULT 'Me',
                    current_weight REAL,
                    target_weight REAL,
                    daily_calories INTEGER DEFAULT 2000,
                    daily_protein INTEGER DEFAULT 150,
                    daily_carbs INTEGER DEFAULT 200,
                    daily_fat INTEGER DEFAULT 65
                );
                CREATE TABLE IF NOT EXISTS meal_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    meal_name TEXT NOT NULL,
                    calories REAL DEFAULT 0,
                    protein REAL DEFAULT 0,
                    carbs REAL DEFAULT 0,
                    fat REAL DEFAULT 0,
                    photo_used INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS workout_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    activity TEXT NOT NULL,
                    duration_min INTEGER DEFAULT 0,
                    calories_burned REAL DEFAULT 0,
                    notes TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS weight_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    weight REAL NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS favorite_meals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meal_name TEXT NOT NULL,
                    calories REAL DEFAULT 0,
                    protein REAL DEFAULT 0,
                    carbs REAL DEFAULT 0,
                    fat REAL DEFAULT 0,
                    times_used INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                );
            """)
    finally:
        conn.close()

init_db()

# ─── Profile ──────────────────────────────────────────────────────────────────

@app.route('/api/profile', methods=['GET'])
def get_profile():
    conn = get_db()
    try:
        row = fetchone(q(conn, 'SELECT * FROM profile WHERE id = 1'))
        return jsonify(row or {})
    finally:
        conn.close()

@app.route('/api/profile', methods=['POST'])
def save_profile():
    d = request.json
    conn = get_db()
    try:
        q(conn, f"""
            INSERT INTO profile (id, name, current_weight, target_weight, daily_calories, daily_protein, daily_carbs, daily_fat)
            VALUES (1, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})
            ON CONFLICT(id) DO UPDATE SET
                name=EXCLUDED.name, current_weight=EXCLUDED.current_weight,
                target_weight=EXCLUDED.target_weight, daily_calories=EXCLUDED.daily_calories,
                daily_protein=EXCLUDED.daily_protein, daily_carbs=EXCLUDED.daily_carbs,
                daily_fat=EXCLUDED.daily_fat
        """, (d.get('name','Me'), d.get('current_weight'), d.get('target_weight'),
              d.get('daily_calories',2000), d.get('daily_protein',150),
              d.get('daily_carbs',200), d.get('daily_fat',65)))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})

# ─── Meal Logs ────────────────────────────────────────────────────────────────

@app.route('/api/logs', methods=['GET'])
def get_logs():
    day = request.args.get('date', date.today().isoformat())
    conn = get_db()
    try:
        rows = fetchall(q(conn, f'SELECT * FROM meal_logs WHERE date = {PH} ORDER BY time ASC', (day,)))
        return jsonify(rows)
    finally:
        conn.close()

@app.route('/api/logs', methods=['POST'])
def add_log():
    d = request.json
    now = datetime.now()
    conn = get_db()
    try:
        cur = q(conn, f"""
            INSERT INTO meal_logs (date, time, meal_name, calories, protein, carbs, fat, photo_used)
            VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})
        """, (now.date().isoformat(), now.strftime('%H:%M'),
              d['meal_name'], d.get('calories',0), d.get('protein',0),
              d.get('carbs',0), d.get('fat',0), 1 if d.get('photo_used') else 0))
        rid = lastid(cur)
        conn.commit()
    except Exception as e:
        try: conn.rollback()
        except: pass
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500
    finally:
        conn.close()
    return jsonify({'id': rid, 'ok': True})

@app.route('/api/logs/<int:log_id>', methods=['DELETE'])
def delete_log(log_id):
    conn = get_db()
    try:
        q(conn, f'DELETE FROM meal_logs WHERE id = {PH}', (log_id,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})

# ─── Workout Logs ─────────────────────────────────────────────────────────────

@app.route('/api/workouts', methods=['GET'])
def get_workouts():
    day = request.args.get('date', date.today().isoformat())
    conn = get_db()
    try:
        rows = fetchall(q(conn, f'SELECT * FROM workout_logs WHERE date = {PH} ORDER BY time ASC', (day,)))
        return jsonify(rows)
    finally:
        conn.close()

@app.route('/api/workouts', methods=['POST'])
def add_workout():
    d = request.json
    now = datetime.now()
    conn = get_db()
    try:
        cur = q(conn, f"""
            INSERT INTO workout_logs (date, time, activity, duration_min, calories_burned, notes)
            VALUES ({PH},{PH},{PH},{PH},{PH},{PH})
        """, (now.date().isoformat(), now.strftime('%H:%M'),
              d['activity'], d.get('duration_min',0), d.get('calories_burned',0), d.get('notes','')))
        rid = lastid(cur)
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': rid, 'ok': True})

@app.route('/api/workouts/<int:workout_id>', methods=['DELETE'])
def delete_workout(workout_id):
    conn = get_db()
    try:
        q(conn, f'DELETE FROM workout_logs WHERE id = {PH}', (workout_id,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})

# ─── Summary ──────────────────────────────────────────────────────────────────

@app.route('/api/summary', methods=['GET'])
def get_summary():
    day = request.args.get('date', date.today().isoformat())
    conn = get_db()
    try:
        food = fetchone(q(conn, f"""
            SELECT COALESCE(SUM(calories),0) as calories, COALESCE(SUM(protein),0) as protein,
                   COALESCE(SUM(carbs),0) as carbs, COALESCE(SUM(fat),0) as fat, COUNT(*) as meal_count
            FROM meal_logs WHERE date = {PH}
        """, (day,)))
        workout = fetchone(q(conn, f'SELECT COALESCE(SUM(calories_burned),0) as calories_burned FROM workout_logs WHERE date = {PH}', (day,)))
    finally:
        conn.close()
    result = food or {}
    result['calories_burned'] = (workout or {}).get('calories_burned', 0)
    result['net_calories'] = result.get('calories', 0) - result['calories_burned']
    return jsonify(result)

# ─── Weight ───────────────────────────────────────────────────────────────────

@app.route('/api/weight', methods=['GET'])
def get_weight():
    conn = get_db()
    try:
        rows = fetchall(q(conn, 'SELECT * FROM weight_logs ORDER BY date DESC LIMIT 30'))
        return jsonify(rows)
    finally:
        conn.close()

@app.route('/api/weight', methods=['POST'])
def add_weight():
    w = request.json.get('weight')
    conn = get_db()
    try:
        q(conn, f'INSERT INTO weight_logs (date, weight) VALUES ({PH},{PH})', (date.today().isoformat(), w))
        q(conn, f'UPDATE profile SET current_weight = {PH} WHERE id = 1', (w,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})

# ─── Favorites ────────────────────────────────────────────────────────────────

@app.route('/api/favorites', methods=['GET'])
def get_favorites():
    conn = get_db()
    try:
        rows = fetchall(q(conn, 'SELECT * FROM favorite_meals ORDER BY times_used DESC, meal_name ASC'))
        return jsonify(rows)
    finally:
        conn.close()

@app.route('/api/favorites', methods=['POST'])
def add_favorite():
    d = request.json
    conn = get_db()
    try:
        existing = fetchone(q(conn, f'SELECT id FROM favorite_meals WHERE LOWER(meal_name) = LOWER({PH})', (d['meal_name'],)))
        if existing:
            return jsonify({'error': 'Already in favorites'}), 409
        cur = q(conn, f'INSERT INTO favorite_meals (meal_name, calories, protein, carbs, fat) VALUES ({PH},{PH},{PH},{PH},{PH})',
                (d['meal_name'], d.get('calories',0), d.get('protein',0), d.get('carbs',0), d.get('fat',0)))
        rid = lastid(cur)
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': rid, 'ok': True})

@app.route('/api/favorites/<int:fav_id>', methods=['DELETE'])
def delete_favorite(fav_id):
    conn = get_db()
    try:
        q(conn, f'DELETE FROM favorite_meals WHERE id = {PH}', (fav_id,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})

@app.route('/api/favorites/<int:fav_id>/log', methods=['POST'])
def log_favorite(fav_id):
    now = datetime.now()
    conn = get_db()
    try:
        fav = fetchone(q(conn, f'SELECT * FROM favorite_meals WHERE id = {PH}', (fav_id,)))
        if not fav:
            return jsonify({'error': 'Not found'}), 404
        q(conn, f'INSERT INTO meal_logs (date, time, meal_name, calories, protein, carbs, fat) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH})',
          (now.date().isoformat(), now.strftime('%H:%M'), fav['meal_name'], fav['calories'], fav['protein'], fav['carbs'], fav['fat']))
        q(conn, f'UPDATE favorite_meals SET times_used = times_used + 1 WHERE id = {PH}', (fav_id,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})

# ─── Anthropic helper ─────────────────────────────────────────────────────────

def get_anthropic_client():
    import anthropic
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        raise ValueError('ANTHROPIC_API_KEY not set in .env')
    return anthropic.Anthropic(api_key=api_key)

def build_context():
    today = date.today().isoformat()
    conn = get_db()
    try:
        p = fetchone(q(conn, 'SELECT * FROM profile WHERE id = 1')) or {}
        s = fetchone(q(conn, f"""
            SELECT COALESCE(SUM(calories),0) as calories, COALESCE(SUM(protein),0) as protein,
                   COALESCE(SUM(carbs),0) as carbs, COALESCE(SUM(fat),0) as fat
            FROM meal_logs WHERE date = {PH}""", (today,))) or {}
        meal_rows  = fetchall(q(conn, f'SELECT meal_name,calories,protein,carbs,fat FROM meal_logs WHERE date={PH} ORDER BY time', (today,)))
        workout_rows = fetchall(q(conn, f'SELECT activity,duration_min,calories_burned FROM workout_logs WHERE date={PH} ORDER BY time', (today,)))
        fav_rows   = fetchall(q(conn, 'SELECT meal_name,calories,protein,carbs,fat FROM favorite_meals ORDER BY times_used DESC'))
    finally:
        conn.close()
    burned = sum(w['calories_burned'] for w in workout_rows)

    meals_text = '\n'.join(
        f"  - {m['meal_name']}: {m['calories']} kcal, {m['protein']}g protein, {m['carbs']}g carbs, {m['fat']}g fat"
        for m in meal_rows
    ) or '  (none yet)'

    workouts_text = '\n'.join(
        f"  - {w['activity']}: {w['duration_min']} min, {w['calories_burned']} kcal burned"
        for w in workout_rows
    ) or '  (none yet)'

    favs_text = '\n'.join(
        f"  - {f['meal_name']}: {f['calories']} kcal, {f['protein']}g P, {f['carbs']}g C, {f['fat']}g F"
        for f in fav_rows
    ) or '  (none saved yet)'

    return f"""You are a personal nutrition and fitness assistant built into the user's NutriTrack app.
You have full context of their day and goals. Be concise, practical, and encouraging.

USER PROFILE:
- Name: {p.get('name', 'User')}
- Current weight: {p.get('current_weight', 'unknown')} kg
- Target weight: {p.get('target_weight', 'unknown')} kg
- Daily goals: {p.get('daily_calories', 2000)} kcal | {p.get('daily_protein', 150)}g protein | {p.get('daily_carbs', 200)}g carbs | {p.get('daily_fat', 65)}g fat

TODAY ({today}):
Eaten so far:
  Calories: {round(s.get('calories', 0))} / {p.get('daily_calories', 2000)} kcal
  Protein:  {round(s.get('protein', 0))} / {p.get('daily_protein', 150)}g
  Carbs:    {round(s.get('carbs', 0))} / {p.get('daily_carbs', 200)}g
  Fat:      {round(s.get('fat', 0))} / {p.get('daily_fat', 65)}g

Meals logged today:
{meals_text}

Workouts logged today:
{workouts_text}
Calories burned: {round(burned)} kcal
Net calories (eaten - burned): {round(s.get('calories', 0) - burned)} kcal

FAVORITE MEALS (saved by user):
{favs_text}

When the user mentions a favorite meal by name, use its saved nutrition values when logging.
When suggesting meals, consider the user's remaining macros for the day.
When asked about workouts or calorie burn, provide realistic estimates and offer to help log them.
Keep responses short and formatted with markdown where helpful."""

# ─── Photo Analysis ───────────────────────────────────────────────────────────

@app.route('/api/analyze', methods=['POST'])
def analyze_photo():
    if 'photo' not in request.files:
        return jsonify({'error': 'No photo provided'}), 400
    try:
        client = get_anthropic_client()
        photo = request.files['photo']
        img_bytes = photo.read()
        img_b64 = base64.standard_b64encode(img_bytes).decode('utf-8')
        media_type = photo.content_type or 'image/jpeg'
        message = client.messages.create(
            model='claude-opus-4-6',
            max_tokens=512,
            messages=[{'role': 'user', 'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': media_type, 'data': img_b64}},
                {'type': 'text', 'text': (
                    'Analyze this image. It may be a meal/food, a nutrition label, or a product package.\n'
                    'Extract nutritional information and return ONLY a JSON object:\n'
                    '{"meal_name":"short name","calories":number,"protein":number,"carbs":number,"fat":number,'
                    '"confidence":"high|medium|low","note":"optional note"}\n'
                    'If it is a nutrition label, read values directly (per serving). '
                    'If it is a meal photo, estimate based on what you see. Return ONLY JSON.'
                )}
            ]}]
        )
        text = message.content[0].text.strip()
        if text.startswith('```'):
            text = text.split('```')[1]
            if text.startswith('json'): text = text[4:]
        return jsonify(json.loads(text.strip()))
    except ValueError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── Workout Photo Analysis ───────────────────────────────────────────────────

@app.route('/api/analyze-workout', methods=['POST'])
def analyze_workout_photo():
    if 'photo' not in request.files:
        return jsonify({'error': 'No photo provided'}), 400
    try:
        client = get_anthropic_client()
        photo = request.files['photo']
        img_bytes = photo.read()
        img_b64 = base64.standard_b64encode(img_bytes).decode('utf-8')
        media_type = photo.content_type or 'image/jpeg'

        conn = get_db()
        try:
            p = fetchone(q(conn, 'SELECT current_weight FROM profile WHERE id = 1')) or {}
        finally:
            conn.close()
        weight_kg = p.get('current_weight') or 75

        message = client.messages.create(
            model='claude-opus-4-6',
            max_tokens=512,
            messages=[{'role': 'user', 'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': media_type, 'data': img_b64}},
                {'type': 'text', 'text': (
                    f'Analyze this workout or training photo. The user weighs approximately {weight_kg} kg.\n'
                    'Identify the exercise or activity shown (gym machine, running, cycling, yoga, etc.).\n'
                    'Estimate a realistic session duration and calories burned based on what you observe.\n'
                    'Return ONLY a JSON object:\n'
                    '{"activity":"exercise name","duration_min":number,"calories_burned":number,'
                    '"notes":"brief observation about the workout","confidence":"high|medium|low","note":"optional caveat"}\n'
                    'If the photo does not show a workout, still return JSON with your best guess and low confidence. Return ONLY JSON.'
                )}
            ]}]
        )
        text = message.content[0].text.strip()
        if text.startswith('```'):
            text = text.split('```')[1]
            if text.startswith('json'): text = text[4:]
        return jsonify(json.loads(text.strip()))
    except ValueError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── AI Chat with tool use ────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "log_meal",
        "description": (
            "Log a meal or food item to today's nutrition tracker. "
            "Use this when the user tells you what they ate, or confirms a meal suggestion. "
            "Estimate nutrition values if not provided."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "meal_name": {"type": "string", "description": "Name of the meal or food"},
                "calories":  {"type": "number", "description": "Total calories (kcal)"},
                "protein":   {"type": "number", "description": "Protein in grams"},
                "carbs":     {"type": "number", "description": "Carbohydrates in grams"},
                "fat":       {"type": "number", "description": "Fat in grams"}
            },
            "required": ["meal_name", "calories", "protein", "carbs", "fat"]
        }
    },
    {
        "name": "save_favorite",
        "description": "Save a meal to the user's favorites list for quick access later. Use when the user says they want to save a meal, or when they mention it's something they eat regularly.",
        "input_schema": {
            "type": "object",
            "properties": {
                "meal_name": {"type": "string"},
                "calories":  {"type": "number"},
                "protein":   {"type": "number"},
                "carbs":     {"type": "number"},
                "fat":       {"type": "number"}
            },
            "required": ["meal_name", "calories", "protein", "carbs", "fat"]
        }
    },
    {
        "name": "log_workout",
        "description": (
            "Log a workout or physical activity to today's tracker. "
            "Use this when the user tells you about exercise they did. "
            "Estimate calories burned based on activity type, duration, and their body weight if available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "activity":       {"type": "string", "description": "Type of activity"},
                "duration_min":   {"type": "number", "description": "Duration in minutes"},
                "calories_burned":{"type": "number", "description": "Estimated calories burned"},
                "notes":          {"type": "string", "description": "Optional notes"}
            },
            "required": ["activity", "duration_min", "calories_burned"]
        }
    }
]

def execute_tool(tool_name, tool_input):
    """Execute a tool call and return a result string."""
    now = datetime.now()
    today = now.date().isoformat()
    time_str = now.strftime('%H:%M')

    if tool_name == 'log_meal':
        conn = get_db()
        try:
            q(conn, f"INSERT INTO meal_logs (date,time,meal_name,calories,protein,carbs,fat) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH})",
              (today, time_str, tool_input['meal_name'], tool_input['calories'], tool_input['protein'], tool_input['carbs'], tool_input['fat']))
            conn.commit()
        finally:
            conn.close()
        return f"Logged: {tool_input['meal_name']} — {tool_input['calories']} kcal, {tool_input['protein']}g P, {tool_input['carbs']}g C, {tool_input['fat']}g F"

    if tool_name == 'save_favorite':
        conn = get_db()
        try:
            existing = fetchone(q(conn, f'SELECT id FROM favorite_meals WHERE LOWER(meal_name)=LOWER({PH})', (tool_input['meal_name'],)))
            if existing:
                return f"'{tool_input['meal_name']}' is already in favorites."
            q(conn, f'INSERT INTO favorite_meals (meal_name,calories,protein,carbs,fat) VALUES ({PH},{PH},{PH},{PH},{PH})',
              (tool_input['meal_name'], tool_input['calories'], tool_input['protein'], tool_input['carbs'], tool_input['fat']))
            conn.commit()
        finally:
            conn.close()
        return f"Saved '{tool_input['meal_name']}' to favorites."

    if tool_name == 'log_workout':
        conn = get_db()
        try:
            q(conn, f"INSERT INTO workout_logs (date,time,activity,duration_min,calories_burned,notes) VALUES ({PH},{PH},{PH},{PH},{PH},{PH})",
              (today, time_str, tool_input['activity'], tool_input['duration_min'], tool_input['calories_burned'], tool_input.get('notes','')))
            conn.commit()
        finally:
            conn.close()
        return f"Logged: {tool_input['activity']} — {tool_input['duration_min']} min, {tool_input['calories_burned']} kcal burned"

    return "Unknown tool"

@app.route('/api/chat', methods=['POST'])
def chat():
    body = request.json
    messages = body.get('messages', [])
    if not messages:
        return jsonify({'error': 'No messages provided'}), 400

    try:
        client = get_anthropic_client()
        system_prompt = build_context()
        logged = []  # track what was auto-logged

        # Agentic loop: keep going until no more tool calls
        while True:
            response = client.messages.create(
                model='claude-opus-4-6',
                max_tokens=1024,
                system=system_prompt,
                tools=TOOLS,
                messages=messages
            )

            # If no tool use, we're done
            if response.stop_reason != 'tool_use':
                reply_text = next((b.text for b in response.content if hasattr(b, 'text')), '')
                return jsonify({'reply': reply_text, 'logged': logged})

            # Process all tool calls in this response
            tool_results = []
            for block in response.content:
                if block.type == 'tool_use':
                    result = execute_tool(block.name, block.input)
                    logged.append({'type': block.name, 'data': block.input, 'result': result})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })

            # Add assistant response + tool results to messages and loop
            messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user",      "content": tool_results}
            ]

    except ValueError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── Serve PWA ────────────────────────────────────────────────────────────────

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f'\n  NutriTrack running at http://localhost:{port}\n')
    app.run(host='0.0.0.0', port=port, debug=False)
