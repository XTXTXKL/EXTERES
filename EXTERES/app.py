import os
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from supabase import create_client, Client
from dotenv import load_dotenv
import humanize
from datetime import datetime, timedelta, timezone

# Load environment variables from .env file
load_dotenv()

# --- Initialize Flask ---
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# --- Connect to Supabase ---
url = os.environ.get("url")
key = os.environ.get("key")

if not url or not key:
    raise ValueError("ERROR: Supabase credentials not found. Please ensure your .env file is in the same directory as app.py and that the variable names are correct (SUPABASE_URL, SUPABASE_KEY).")

supabase: Client = create_client(url, key)

app.jinja_env.filters['humanize'] = humanize.naturaltime

# --- Decorator to Protect Routes ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session or 'access_token' not in session:
            flash("You must be logged in to view this page.", "warning")
            return redirect(url_for('auth'))
        
        try:
            supabase.auth.set_session(session['access_token'], session.get('refresh_token'))
        except Exception as e:
            print(f"DEBUG: Failed to set Supabase session, redirecting to login. Error: {e}")
            session.clear()
            flash("Your session has expired. Please log in again.", "info")
            return redirect(url_for('auth'))
            
        return f(*args, **kwargs)
    return decorated_function


# --- Frontend and Auth Routes (No changes here) ---
@app.route("/")
def home():
    return render_template("productivity_app_homepage.html")

@app.route("/features")
def features():
    return render_template("features.html")

@app.route("/about")
def about():
    return render_template("about.html")

# Add these new routes to your app.py file

@app.route("/profile")
@login_required
def profile():
    """Renders the profile page with the user's name and email."""
    user_email = session['user']['email']
    user_name = user_email.split('@')[0].capitalize() # Default name

    # Try to get the full name from the profiles table if it exists
    try:
        user_id = session['user']['id']
        response = supabase.table("profiles").select("full_name").eq("id", user_id).single().execute()
        if response.data and response.data.get('full_name'):
            user_name = response.data['full_name']
    except Exception:
        pass # If profile doesn't exist, use the default name

    return render_template("profile.html", user_email=user_email, user_name=user_name)


@app.route("/api/profile", methods=["GET", "PUT"])
@login_required
def handle_profile():
    """Handles fetching and updating user profile data from the 'profiles' table."""
    user_id = session['user']['id']

    if request.method == "GET":
        try:
            response = supabase.table("profiles").select("full_name, bio").eq("id", user_id).single().execute()
            return jsonify(response.data or {"full_name": "", "bio": ""})
        except Exception:
            # If the .single() query finds no rows, it can raise an error.
            # We return default values in that case.
            return jsonify({"full_name": "", "bio": ""})

    if request.method == "PUT":
        try:
            data = request.get_json()
            full_name = data.get("full_name")
            bio = data.get("bio")

            if not full_name or not full_name.strip():
                return jsonify({"error": "Full name cannot be empty."}), 400

            # Upsert creates the profile if it doesn't exist, or updates it if it does.
            response = supabase.table("profiles").upsert({
                "id": user_id,
                "full_name": full_name,
                "bio": bio,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).execute()
            
            return jsonify(response.data[0]), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route("/pricing")
def pricing():
    return render_template("pricing.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route("/integrations")
def integrations():
    return render_template("integrations.html")

@app.route("/updates")
def updates():
    return render_template("updates.html")

@app.route("/auth", methods=["GET", "POST"])
def auth():
    if request.method == "POST":
        form_type = request.form.get("form_type")
        email = request.form.get("email")
        password = request.form.get("password")

        if form_type == "signup":
            try:
                supabase.auth.sign_up({"email": email, "password": password})
                return redirect(url_for('verification_notice', email=email))
            except Exception as e:
                error_message = str(e)
                if 'User already registered' in error_message:
                    error_message = "A user with this email already exists."
                return render_template("auth.html", form_type="signup", error=error_message)

        elif form_type == "login":
            try:
                data = supabase.auth.sign_in_with_password({"email": email, "password": password})
                session['user'] = data.session.user.dict()
                session['access_token'] = data.session.access_token
                session['refresh_token'] = data.session.refresh_token
                return redirect(url_for('dashboard'))
            except Exception:
                return render_template("auth.html", form_type="login", error="Invalid credentials. Please try again.")

    return render_template("auth.html", form_type="login")

# Add these new routes to your app.py file


@app.route("/verification-notice")
def verification_notice():
    user_email = request.args.get('email')
    return render_template("verification_notice.html", email=user_email)


@app.route("/resend-verification")
def resend_verification():
    email = request.args.get('email')
    if email:
        try:
            flash("If your account exists, a verification link has been sent.", "success")
        except Exception as e:
            print(f"Error during resend action for {email}: {e}")
            flash("An error occurred. Please try again later.", "error")
    
    return redirect(url_for('verification_notice', email=email))


@app.route("/callback")
def callback():
    return render_template("callback.html")


@app.route("/token-signin", methods=["POST"])
def token_signin():
    try:
        data = request.get_json()
        access_token = data.get('access_token')
        refresh_token = data.get('refresh_token')

        if not access_token or not refresh_token:
            return jsonify({"success": False, "error": "Missing tokens"}), 400
        
        session_data = supabase.auth.set_session(access_token, refresh_token)
        session['user'] = session_data.user.dict()
        session['access_token'] = session_data.session.access_token
        session['refresh_token'] = session_data.session.refresh_token
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

def parse_timestamp(ts_str):
    if not ts_str: return None
    try:
        # Handles timestamps with or without 'Z'
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None

@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session['user']['id']
    user_email = session['user']['email']
    user_name = user_email.split('@')[0].capitalize() # Default name
    
    # Fetch user's full name
    try:
        response = supabase.table("profiles").select("full_name").eq("id", user_id).single().execute()
        if response.data and response.data.get('full_name'):
            user_name = response.data['full_name']
    except Exception as e:
        print(f"DEBUG: Could not fetch profile name for dashboard, using default. Error: {e}")
        pass
    
    # --- Fetch Tasks & Calculate Task Stats ---
    try:
        response = supabase.table("tasks").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        tasks = response.data
    except Exception as e:
        print(f"Error fetching tasks: {e}")
        tasks = []

    tasks_completed = [task for task in tasks if task.get('is_complete')]
    tasks_completed_count = len(tasks_completed)
    active_tasks_count = len(tasks) - tasks_completed_count
    total_tasks = len(tasks)

    today = datetime.now(timezone.utc)
    start_of_this_week = today - timedelta(days=today.weekday())
    start_of_last_week = start_of_this_week - timedelta(days=7)
    
    # Calculate task percentage change
    tasks_this_week_count = 0
    tasks_last_week_count = 0
    for task in tasks_completed:
        completed_at = parse_timestamp(task.get('completed_at'))
        if completed_at:
            if completed_at >= start_of_this_week:
                tasks_this_week_count += 1
            elif start_of_last_week <= completed_at < start_of_this_week:
                tasks_last_week_count += 1
    
    task_percentage_change = 0
    if tasks_last_week_count > 0:
        task_percentage_change = round(((tasks_this_week_count - tasks_last_week_count) / tasks_last_week_count) * 100)
    elif tasks_this_week_count > 0:
        task_percentage_change = 100

    # --- NEW: Fetch Focus Sessions & Calculate Stats ---
    try:
        response = supabase.table("focus_sessions").select("duration_minutes, created_at").eq("user_id", user_id).execute()
        focus_sessions = response.data
    except Exception as e:
        print(f"Error fetching focus sessions: {e}")
        focus_sessions = []
    
    total_focus_minutes = 0
    focus_this_week_min = 0
    focus_last_week_min = 0
    
    for focus_session in focus_sessions:
        # Use .get() to provide a default value of 0 if the key is missing
        duration = focus_session.get('duration_minutes', 0)
        
        total_focus_minutes += duration
        created_at = parse_timestamp(focus_session.get('created_at'))
        if created_at:
            if created_at >= start_of_this_week:
                focus_this_week_min += duration
            elif start_of_last_week <= created_at < start_of_this_week:
                focus_last_week_min += duration
                
    total_focus_hours = round(total_focus_minutes / 60, 1)

    focus_percentage_change = 0
    if focus_last_week_min > 0:
        focus_percentage_change = round(((focus_this_week_min - focus_last_week_min) / focus_last_week_min) * 100)
    elif focus_this_week_min > 0:
        focus_percentage_change = 100

    # --- NEW: Calculate Productivity Score ---
    # We define this as a weighted average:
    # 70% based on task completion rate.
    # 30% based on focus time (scaled to 100, capping at 20 hours).
    
    task_score = 0
    if total_tasks > 0:
        task_score = (tasks_completed_count / total_tasks) * 100
        
    # Scales 20 hours of focus to a "100" score (100 / 20 = 5)
    focus_score = min(total_focus_hours * 5, 100) 
    
    productivity_score = round((task_score * 0.7) + (focus_score * 0.3))

    # --- Generate recent activities ---
    recent_activities = []
    for task in tasks_completed: # Only show completed tasks in activity
        completed_at = parse_timestamp(task.get('completed_at'))
        if completed_at:
            recent_activities.append({
                'description': f'You completed task "{task["title"]}"',
                'timestamp': completed_at
            })
    recent_activities.sort(key=lambda x: x['timestamp'], reverse=True)
    
    # --- Render Template with All New Data ---
    return render_template(
        "dashboard.html", 
        user_email=user_email, 
        user_name=user_name,
        tasks=tasks,
        tasks_completed_count=tasks_completed_count,
        active_tasks_count=active_tasks_count,
        percentage_change=task_percentage_change, # Renamed for clarity
        recent_activities=recent_activities[:10],
        total_focus_hours=total_focus_hours, # <-- NEW
        focus_percentage_change=focus_percentage_change, # <-- NEW
        productivity_score=productivity_score # <-- NEW
    )

# Add this route to app.py

@app.route("/focus")
@login_required
def focus():
    """Renders the distraction-free focus session page."""
    user_id = session['user']['id']
    
    # --- 1. Get Task info from URL (if it exists) ---
    task_id = request.args.get('task_id')
    task_title = request.args.get('task_title', 'Select a task to begin') # Default text
    duration_min = request.args.get('duration', 25, type=int)

    # --- 2. Fetch User's Historical Stats ---
    tasks_completed_count = 0
    sessions_completed_count = 0
    total_focus_minutes = 0

    try:
        # Get task stats
        task_response = supabase.table("tasks").select("is_complete").eq("user_id", user_id).execute()
        if task_response.data:
            tasks_completed_count = sum(1 for task in task_response.data if task.get('is_complete'))
        
        # Get focus stats
        focus_response = supabase.table("focus_sessions").select("duration_minutes").eq("user_id", user_id).execute()
        if focus_response.data:
            sessions_completed_count = len(focus_response.data)
            total_focus_minutes = sum(sess.get('duration_minutes', 0) for sess in focus_response.data)
            
    except Exception as e:
        print(f"Error fetching stats for focus page: {e}")
        pass # Will use defaults of 0

    # --- 3. Render page with all data ---
    return render_template(
        "focus.html", 
        task_id=task_id,
        task_title=task_title,
        duration_min=duration_min,
        tasks_completed_count=tasks_completed_count,
        sessions_completed_count=sessions_completed_count,
        total_focus_minutes=total_focus_minutes
    )

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('home'))


# --- API Routes for Tasks ---
@app.route("/api/tasks", methods=["GET"])
@login_required
def get_tasks():
    try:
        response = supabase.table("tasks").select("*").order("created_at", desc=True).execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/events", methods=["GET"])
@login_required
def get_events():
    """Return all events for the logged-in user."""
    try:
        user_id = session['user']['id']
        response = supabase.table("events").select("*").eq("user_id", user_id).order("start_time").execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/events", methods=["POST"])
@login_required
def add_event():
    """Add a new event (meeting, lecture, etc.)"""
    try:
        data = request.get_json()
        user_id = session['user']['id']

        title = data.get("title")
        start_time = data.get("start_time")
        end_time = data.get("end_time")
        description = data.get("description", "")

        if not title or not start_time or not end_time:
            return jsonify({"error": "Missing required fields"}), 400

        response = supabase.table("events").insert({
            "user_id": user_id,
            "title": title,
            "description": description,
            "start_time": start_time,
            "end_time": end_time
        }).execute()

        return jsonify(response.data[0]), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/events/<int:event_id>", methods=["PUT"])
@login_required
def update_event(event_id):
    """Edit event details or notes."""
    try:
        user_id = session['user']['id']
        data = request.get_json()
        data["updated_at"] = datetime.now(timezone.utc).isoformat()

        response = supabase.table("events").update(data).eq("id", event_id).eq("user_id", user_id).execute()

        if not response.data:
            return jsonify({"error": "Event not found"}), 404

        return jsonify(response.data[0])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/events/<int:event_id>", methods=["DELETE"])
@login_required
def delete_event(event_id):
    """Delete a scheduled event."""
    try:
        user_id = session['user']['id']
        response = supabase.table("events").delete().eq("id", event_id).eq("user_id", user_id).execute()

        if not response.data:
            return jsonify({"error": "Event not found"}), 404

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/tasks", methods=["POST"])
@login_required
def add_task():
    try:
        data = request.get_json()
        if not data or "title" not in data:
            return jsonify({"error": "Task title is required."}), 400
            
        user_id = session['user']['id']
        priority = data.get("priority", "Medium")
        
        response = supabase.table("tasks").insert({
            "title": data["title"],
            "user_id": user_id,
            "is_complete": False,  # <-- FIX #1: Changed from is_completed
            "priority": priority
        }).execute()
        
        return jsonify(response.data[0]), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/calendar")
@login_required
def calendar():
    """Render the event calendar page."""
    user_id = session['user']['id']

    # Fetch events for this user
    try:
        response = supabase.table("events").select("*").eq("user_id", user_id).order("start_time").execute()
        events = response.data or []
    except Exception as e:
        print(f"Error fetching events: {e}")
        events = []

    return render_template("calendar.html", events=events)

@app.route("/api/tasks/<int:task_id>/complete", methods=["PUT"])
@login_required
def complete_task(task_id):
    try:
        user_id = session['user']['id']
        
        response = supabase.table("tasks").update({
            "is_complete": True,  # <-- FIX #2: Changed from is_completed
            "completed_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", task_id).eq("user_id", user_id).execute()
        
        if not response.data:
            return jsonify({"error": "Task not found or permission denied"}), 404
            
        return jsonify(response.data[0])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- API Routes for Projects and Focus Time (No changes here) ---
@app.route("/api/projects", methods=["GET"])
@login_required
def get_projects():
    try:
        response = supabase.table("projects").select("*").order("created_at", desc=True).execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/projects", methods=["POST"])
@login_required
def add_project():
    try:
        data = request.get_json()
        if not data or "name" not in data:
            return jsonify({"error": "Project name is required."}), 400
        user_id = session['user']['id']
        response = supabase.table("projects").insert({
            "name": data["name"],
            "user_id": user_id
        }).execute()
        return jsonify(response.data[0]), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/focus", methods=["POST"])
@login_required
def add_focus_session():
    try:
        data = request.get_json()
        if not data or "duration_minutes" not in data:
            return jsonify({"error": "Duration in minutes is required."}), 400
        user_id = session['user']['id']
        focus_data = {
            "user_id": user_id,
            "duration_minutes": data["duration_minutes"]
        }
        if data.get("task_id"):
            focus_data["task_id"] = data.get("task_id")
        if data.get("project_id"):
            focus_data["project_id"] = data.get("project_id")
        response = supabase.table("focus_sessions").insert(focus_data).execute()
        return jsonify(response.data[0]), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
        
@app.route("/api/focus", methods=["GET"])
@login_required
def get_focus_sessions():
    try:
        response = supabase.table("focus_sessions").select("*").order("created_at", desc=True).execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Run the App ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)