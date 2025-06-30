from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for
from flask_cors import CORS # To handle Cross-Origin Resource Sharing if frontend and backend are on different ports during dev
import xml.etree.ElementTree as ET
import os
import json
import requests
import logging
import anthropic
import shutil
from datetime import datetime
from functools import wraps

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.secret_key = 'HomePay_AI_Admin_Secret_Key_2025'  # Change this in production
CORS(app)# This will allow all origins. For production, configure it more securely.

OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434')
LLM_MODEL = os.getenv('LLM_MODEL', 'llama3.2:3b')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
USE_HYBRID_LLM = os.getenv('USE_HYBRID_LLM', 'true').lower() == 'true'

KNOWLEDGE_BASE_FILE = 'knowledge_base.json'
MODEL_INSTRUCTIONS_FILE = 'model_instructions.json'
REPRESENTATIVE_SETTINGS_FILE = 'representative_settings.json'
BACKUP_DIR = 'backups'

response_cache = {}

def get_cached_response(user_message):
    """Get cached response for frequently asked questions - temporarily disabled for testing"""
    return None
    # message_key = user_message.lower().strip()
    # return response_cache.get(message_key)

def cache_response(user_message, response):
    """Cache response for future use"""
    message_key = user_message.lower().strip()
    response_cache[message_key] = response

    if len(response_cache) > 100:
        oldest_key = next(iter(response_cache))
        del response_cache[oldest_key]

@app.route('/')
def serve_index():
    """Serve the main index.html page"""
    return send_from_directory('.', 'index.html')

@app.route('/client/<path:filename>')
def serve_client_files(filename):
    """Serve static files from the client directory"""
    return send_from_directory('client', filename)

@app.route('/homepay_guide_buyer.xml')
def serve_guide_xml():
    """Serve the guide XML file"""
    return send_from_directory('.', 'homepay_guide_buyer.xml')

@app.route('/admin/login')
def admin_login_page():
    """Serve the admin login page"""
    return send_from_directory('.', 'admin_login.html')

@app.route('/admin/login', methods=['POST'])
def admin_login():
    """Handle admin login authentication"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        password = data.get('password', '')

        if email == 'admin@homepay.co.il' and password == 'HomePay23':
            session['admin_authenticated'] = True
            session['admin_email'] = email
            session['login_time'] = datetime.now().isoformat()

            app.logger.info(f"Admin login successful for {email}")
            return jsonify({
                'success': True,
                'message': 'התחברות בוצעה בהצלחה'
            })
        else:
            app.logger.warning(f"Failed login attempt for email: {email}")
            return jsonify({
                'success': False,
                'message': 'כתובת דואר אלקטרוני או סיסמה שגויים'
            }), 401

    except Exception as e:
        app.logger.error(f"Login error: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'שגיאה בשרת. אנא נסה שוב.'
        }), 500

@app.route('/admin/logout')
def admin_logout():
    """Handle admin logout"""
    session.clear()
    return redirect('/admin/login')

def require_admin_auth(f):
    """Decorator to require admin authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_authenticated'):
            return redirect('/admin/login')
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin')
@require_admin_auth
def admin_interface():
    """Serve admin interface (protected)"""
    return send_from_directory('.', 'admin_interface.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get('message')

        if not user_message:
            return jsonify({'error': 'No message provided'}), 400

        # TODO: In a real application, you would process the user_message
        # and interact with a language model here.
        # For now, we'll just echo the message or send a fixed reply.

        # Example: Simple echo response for demonstration
        # ai_reply = f"קיבלתי את הודעתך: \"{user_message}\". אני עדיין בפיתוח."

        ai_reply = get_homepay_response(user_message)

        if ai_reply:
            try:
                if '\\u' in ai_reply:
                    ai_reply = ai_reply.encode().decode('unicode_escape')
                ai_reply = ai_reply.encode('utf-8').decode('utf-8')
            except Exception as encoding_error:
                app.logger.warning(f"Encoding issue with response: {encoding_error}")
                pass

        return jsonify({'reply': ai_reply})

    except Exception as e:
        app.logger.error(f"Error in /api/chat: {e}")
        return jsonify({'error': 'An internal server error occurred'}), 500

def load_knowledge_base():
    """Load Q&A pairs from knowledge base file - dynamic loading on each request"""
    try:
        kb_path = os.path.join(os.path.dirname(__file__), KNOWLEDGE_BASE_FILE)
        with open(kb_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        app.logger.error(f"Error loading knowledge base: {e}")
        return {"qa_pairs": []}

def load_model_instructions():
    """Load model instructions from JSON file - dynamic loading on each request"""
    try:
        inst_path = os.path.join(os.path.dirname(__file__), MODEL_INSTRUCTIONS_FILE)
        with open(inst_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('instructions', '')
    except FileNotFoundError:
        app.logger.error("Model instructions file not found")
        return "אתה סוכן תמיכה AI של HomePay לתשלום שוברי חוק מכר. ענה בעברית בלבד."
    except json.JSONDecodeError:
        app.logger.error("Invalid JSON in model instructions file")
        return "אתה סוכן תמיכה AI של HomePay לתשלום שוברי חוק מכר. ענה בעברית בלבד."

def load_representative_settings():
    """Load representative settings from JSON file - dynamic loading on each request"""
    try:
        rep_path = os.path.join(os.path.dirname(__file__), REPRESENTATIVE_SETTINGS_FILE)
        with open(rep_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        default_settings = {
            "name": "סוכן HomePay",
            "gender": "male",
            "communication_style": "young_friendly",
            "profile_picture": "assets/hplogo.png",
            "last_updated": datetime.now().isoformat()
        }
        try:
            with open(REPRESENTATIVE_SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            app.logger.error(f"Failed to create default representative settings: {e}")
        return default_settings
    except json.JSONDecodeError:
        app.logger.error("Invalid JSON in representative settings file")
        return {"name": "סוכן HomePay", "gender": "male", "communication_style": "young_friendly", "profile_picture": "assets/hplogo.png"}

def create_backup():
    """Create backup of current configuration files"""
    try:
        if not os.path.exists(BACKUP_DIR):
            os.makedirs(BACKUP_DIR)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        if os.path.exists(KNOWLEDGE_BASE_FILE):
            backup_kb = os.path.join(BACKUP_DIR, f'knowledge_base_{timestamp}.json')
            shutil.copy2(KNOWLEDGE_BASE_FILE, backup_kb)

        if os.path.exists(MODEL_INSTRUCTIONS_FILE):
            backup_inst = os.path.join(BACKUP_DIR, f'model_instructions_{timestamp}.json')
            shutil.copy2(MODEL_INSTRUCTIONS_FILE, backup_inst)

        if os.path.exists(REPRESENTATIVE_SETTINGS_FILE):
            backup_rep = os.path.join(BACKUP_DIR, f'representative_settings_{timestamp}.json')
            shutil.copy2(REPRESENTATIVE_SETTINGS_FILE, backup_rep)

        return timestamp
    except Exception as e:
        app.logger.error(f"Backup creation failed: {e}")
        return None

def find_relevant_kb_entries(user_message, kb):
    """Find relevant knowledge base entries using keyword matching"""
    user_words = set(user_message.lower().split())
    relevant_entries = []

    for qa in kb.get('qa_pairs', []):
        keywords = [kw.lower() for kw in qa.get('keywords', [])]
        keyword_matches = sum(1 for kw in keywords if any(word in kw or kw in word for word in user_words))

        question_words = set(qa['question'].lower().split())
        question_matches = len(user_words.intersection(question_words))

        relevance_score = keyword_matches * 2 + question_matches

        if relevance_score > 0:
            relevant_entries.append((qa, relevance_score))

    relevant_entries.sort(key=lambda x: x[1], reverse=True)
    return [entry[0] for entry in relevant_entries[:3]]  # Return top 3 most relevant

def get_homepay_response(user_message):
    """Generate contextual responses using hybrid LLM approach (local Ollama + Anthropic fallback) with caching"""

    cached_response = get_cached_response(user_message)
    if cached_response:
        app.logger.info(f"Returning cached response for: {user_message[:50]}...")
        return cached_response

    kb = load_knowledge_base()
    relevant_entries = find_relevant_kb_entries(user_message, kb)
    if relevant_entries:
        app.logger.info(f"Found {len(relevant_entries)} relevant KB entries for: {user_message[:50]}...")
    else:
        app.logger.warning(f"No relevant KB entries found for: {user_message[:50]}...")

    local_response = try_local_llm(user_message, relevant_entries)
    if local_response:
        cache_response(user_message, local_response)
        return local_response

    if USE_HYBRID_LLM and ANTHROPIC_API_KEY:
        anthropic_response = try_anthropic_llm(user_message, relevant_entries)
        if anthropic_response:
            cache_response(user_message, anthropic_response)
            return anthropic_response

    app.logger.warning("Both LLM methods failed, using keyword matching fallback")
    fallback_response = get_fallback_response(user_message)
    cache_response(user_message, fallback_response)
    return fallback_response

def try_local_llm(user_message, relevant_entries=None):
    """Try local Ollama LLM"""
    try:
        kb = load_knowledge_base()
        instructions = load_model_instructions()
        rep_settings = load_representative_settings()

        kb_entries = relevant_entries if relevant_entries else kb.get('qa_pairs', [])

        gender_text = "נציג זכר" if rep_settings.get('gender') == 'male' else "נציגה נקבה"
        style_instructions = ""

        if rep_settings.get('communication_style') == 'young_friendly':
            style_instructions = """
סגנון תקשורת: צעיר וחברותי
- השתמש בשפה קלילה וחברותית
- הוסף אמוג'י מתאימים לפעמים
- דבר בטון חם ונגיש
- השתמש בביטויים כמו "בטח!", "מעולה!", "אין בעיה"
"""
        else:  # formal_professional
            style_instructions = """
סגנון תקשורת: רשמי ושירותי
- השתמש בשפה מקצועית ומנומסת
- דבר בטון רשמי אך חם
- השתמש בביטויים כמו "אשמח לעזור", "בכבוד רב", "לשירותכם"
- הקפד על נימוס ומקצועיות
"""

        context = f"{instructions}\n\n"
        context += f"אתה {gender_text} במערכת HomePay.\n"
        context += style_instructions
        context += "\nתכונות קבועות שלך:\n"
        context += "- מקצועי ומומחה במערכת HomePay\n"
        context += "- ידידותי ותומך\n"
        context += "- מעודד שימוש במערכת הדיגיטלית\n"
        context += "- סבלני ומסביר בבירור\n\n"
        context += "בסיס הידע שלך (חשוב לעיין בו בקפידה לפני מתן תשובה):\n"
        context += "=" * 50 + "\n"
        if relevant_entries:
            context += f"נמצאו {len(kb_entries)} פריטי ידע רלוונטיים לשאלתך:\n\n"
        for i, qa in enumerate(kb_entries, 1):
            keywords_text = ", ".join(qa.get('keywords', []))
            context += f"פריט ידע #{i}:\n"
            context += f"מילות מפתח: {keywords_text}\n"
            context += f"שאלה: {qa['question']}\n"
            context += f"תשובה: {qa['answer']}\n"
            context += "-" * 30 + "\n\n"
        context += "=" * 50 + "\n"

        prompt = f"""{context}

הוראות חשובות לעיבוד השאלה:
1. קרא בעיון את שאלת המשתמש: "{user_message}"
2. חפש בבסיס הידע שלעיל פריטי ידע רלוונטיים על ידי השוואת:
   - מילות המפתח של כל פריט ידע
   - תוכן השאלות הקיימות
   - נושאי התשובות
3. אם מצאת פריט ידע רלוונטי - השתמש בתשובה שלו כבסיס למענה שלך
4. אם לא מצאת פריט ידע רלוונטי - אמר בבירור שאין לך מידע על הנושא

כללי מענה:
- חשוב מאוד: ענה רק על בסיס המידע הקיים בבסיס הידע שלעיל
- אל תמציא מידע, מספרי טלפון, כתובות או פרטים שאינם קיימים במערכת
- אם אינך יודע תשובה מדויקת על בסיס בסיס הידע, אמר בבירור שאתה לא יודע ותפנה את המשתמש לתמיכה אנושית
- אל תנחש או תמציא פרטים טכניים, מספרי טלפון, כתובות או מידע שאינו מופיע במפורש בבסיס הידע
- תן תשובה בפורמט HTML עם פסקאות <p> ורשימות <ul><li>
- אם התשובה יכולה להיות מועילה יותר עם תמונה, השתמש בתג HTML: <img src="/client/images/filename.png" alt="תיאור התמונה" style="max-width:300px;margin:10px 0;">
- תמונות זמינות: 01_login_screen.png, 02_login_filled.png, 03_login_processing.png, 04_otp_verification.png, 05_otp_filled_processing.png, 06_main_dashboard_apartment_details.png, 07_payments_screen.png, 08_payments_scrolled_more_vouchers.png, 09_payments_more_vouchers_765k_665k.png
- השתמש בתמונות רק כשהן רלוונטיות לשאלה

תשובה מפורטת בפורמט HTML (על בסיס בסיס הידע בלבד):"""

        response = requests.post(f'{OLLAMA_URL}/api/generate',
            json={
                'model': LLM_MODEL,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.7,
                    'top_p': 0.9,
                    'num_predict': 800
                }
            },
            timeout=15,
            headers={'Content-Type': 'application/json; charset=utf-8'}
        )

        if response.status_code == 200:
            result = response.json()
            llm_response = result.get('response', '').strip()
            if llm_response:
                try:
                    if '\\u' in llm_response:
                        llm_response = llm_response.encode().decode('unicode_escape')
                    llm_response = llm_response.encode('utf-8').decode('utf-8')
                except:
                    pass
                app.logger.info(f"Local LLM response generated for: {user_message[:50]}...")
                return llm_response
        else:
            app.logger.error(f"Local LLM API error: {response.status_code} - {response.text}")

    except Exception as e:
        app.logger.error(f"Local LLM integration error: {e}")

    return None

def try_anthropic_llm(user_message, relevant_entries=None):
    """Try Anthropic Claude API as fallback"""
    try:
        kb = load_knowledge_base()
        instructions = load_model_instructions()
        rep_settings = load_representative_settings()

        kb_entries = relevant_entries if relevant_entries else kb.get('qa_pairs', [])

        gender_text = "נציג זכר" if rep_settings.get('gender') == 'male' else "נציגה נקבה"
        style_instructions = ""

        if rep_settings.get('communication_style') == 'young_friendly':
            style_instructions = """
סגנון תקשורת: צעיר וחברותי
- השתמש בשפה קלילה וחברותית
- הוסף אמוג'י מתאימים לפעמים
- דבר בטון חם ונגיש
- השתמש בביטויים כמו "בטח!", "מעולה!", "אין בעיה"
"""
        else:  # formal_professional
            style_instructions = """
סגנון תקשורת: רשמי ושירותי
- השתמש בשפה מקצועית ומנומסת
- דבר בטון רשמי אך חם
- השתמש בביטויים כמו "אשמח לעזור", "בכבוד רב", "לשירותכם"
- הקפד על נימוס ומקצועיות
"""

        context = f"{instructions}\n\n"
        context += f"אתה {gender_text} במערכת HomePay.\n"
        context += style_instructions
        context += "\nתכונות קבועות שלך:\n"
        context += "- מקצועי ומומחה במערכת HomePay\n"
        context += "- ידידותי ותומך\n"
        context += "- מעודד שימוש במערכת הדיגיטלית\n"
        context += "- סבלני ומסביר בבירור\n\n"
        context += "בסיס הידע שלך (חשוב לעיין בו בקפידה לפני מתן תשובה):\n"
        context += "=" * 50 + "\n"
        if relevant_entries:
            context += f"נמצאו {len(kb_entries)} פריטי ידע רלוונטיים לשאלתך:\n\n"
        for i, qa in enumerate(kb_entries, 1):
            keywords_text = ", ".join(qa.get('keywords', []))
            context += f"פריט ידע #{i}:\n"
            context += f"מילות מפתח: {keywords_text}\n"
            context += f"שאלה: {qa['question']}\n"
            context += f"תשובה: {qa['answer']}\n"
            context += "-" * 30 + "\n\n"
        context += "=" * 50 + "\n"

        prompt = f"""{context}

הוראות חשובות לעיבוד השאלה:
1. קרא בעיון את שאלת המשתמש: "{user_message}"
2. חפש בבסיס הידע שלעיל פריטי ידע רלוונטיים על ידי השוואת:
   - מילות המפתח של כל פריט ידע
   - תוכן השאלות הקיימות
   - נושאי התשובות
3. אם מצאת פריט ידע רלוונטי - השתמש בתשובה שלו כבסיס למענה שלך
4. אם לא מצאת פריט ידע רלוונטי - אמר בבירור שאין לך מידע על הנושא

כללי מענה:
- חשוב מאוד: ענה רק על בסיס המידע הקיים בבסיס הידע שלעיל
- אל תמציא מידע, מספרי טלפון, כתובות או פרטים שאינם קיימים במערכת
- אם אינך יודע תשובה מדויקת על בסיס בסיס הידע, אמר בבירור שאתה לא יודע ותפנה את המשתמש לתמיכה אנושית
- אל תנחש או תמציא פרטים טכניים, מספרי טלפון, כתובות או מידע שאינו מופיע במפורש בבסיס הידע
- תן תשובה בפורמט HTML עם פסקאות <p> ורשימות <ul><li>
- אם התשובה יכולה להיות מועילה יותר עם תמונה, השתמש בתג HTML: <img src="/client/images/filename.png" alt="תיאור התמונה" style="max-width:300px;margin:10px 0;">
- תמונות זמינות: 01_login_screen.png, 02_login_filled.png, 03_login_processing.png, 04_otp_verification.png, 05_otp_filled_processing.png, 06_main_dashboard_apartment_details.png, 07_payments_screen.png, 08_payments_scrolled_more_vouchers.png, 09_payments_more_vouchers_765k_665k.png
- השתמש בתמונות רק כשהן רלוונטיות לשאלה

תשובה מפורטת בפורמט HTML (על בסיס בסיס הידע בלבד):"""

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=15.0)
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=800,
            temperature=0.7,
            system="אתה סוכן תמיכה של HomePay. ענה בעברית בלבד. חשוב מאוד: ענה רק על בסיס המידע שמופיע בבסיס הידע. אל תמציא מידע שאינו קיים.",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        if response.content and response.content[0].text:
            anthropic_response = response.content[0].text.strip()
            if anthropic_response:
                app.logger.info(f"Anthropic LLM response generated for: {user_message[:50]}...")
                return anthropic_response

    except Exception as e:
        app.logger.error(f"Anthropic LLM integration error: {e}")

    return None

def log_unknown_question(user_message):
    """Log questions that the agent couldn't answer"""
    try:
        unknown_questions_file = os.path.join(os.path.dirname(__file__), 'unknown_questions.json')

        unknown_questions = []
        if os.path.exists(unknown_questions_file):
            try:
                with open(unknown_questions_file, 'r', encoding='utf-8') as f:
                    unknown_questions = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                unknown_questions = []

        new_question = {
            "id": len(unknown_questions) + 1,
            "question": user_message,
            "timestamp": datetime.now().isoformat(),
            "resolved": False
        }

        unknown_questions.append(new_question)

        with open(unknown_questions_file, 'w', encoding='utf-8') as f:
            json.dump(unknown_questions, f, ensure_ascii=False, indent=2)

        app.logger.info(f"Logged unknown question: {user_message}")

    except Exception as e:
        app.logger.error(f"Failed to log unknown question: {e}")

def get_fallback_response(user_message):
    """Fallback to keyword matching if LLM fails"""
    message_lower = user_message.lower()
    message_words = set(message_lower.split())

    kb = load_knowledge_base()
    best_match = None
    best_score = 0
    
    for qa in kb.get('qa_pairs', []):
        keywords = [kw.lower() for kw in qa.get('keywords', [])]
        keyword_matches = sum(1 for kw in keywords if any(word in kw or kw in word for word in message_words))
        
        question_words = set(qa['question'].lower().split())
        question_matches = len(message_words.intersection(question_words))
        
        relevance_score = keyword_matches * 2 + question_matches
        
        if relevance_score > best_score:
            best_score = relevance_score
            best_match = qa
    
    if best_match and best_score >= 2:
        return best_match['answer']

    if any(word in message_lower for word in ["שלום", "היי", "בוקר טוב", "ערב טוב"]):
        return "שלום! אני סוכן התמיכה הדיגיטלי של HomePay. אני כאן לעזור לך עם תהליך התשלום של שוברי חוק המכר. איך אני יכול לעזור לך?"

    if any(word in message_lower for word in ["התחברות", "לוגין", "כניסה", "סיסמה", "קוד"]):
        return """להתחברות למערכת HomePay:
1. הזן את מספר הטלפון ומספר תעודת הזהות שלך
2. לחץ על 'שלח' לקבלת קוד אימות
3. הזן את קוד האימות בן 4 הספרות שנשלח לטלפון
4. לחץ על 'לאמת' להשלמת ההתחברות

אם אתה מתקשה בהתחברות, וודא שהפרטים נכונים ושהטלפון זמין לקבלת SMS."""

    if any(word in message_lower for word in ["תשלום", "שלם", "כסף", "סכום", "שובר"]):
        return """לביצוע תשלום במערכת HomePay:
1. עבור לעמוד התשלומים ובחר את השובר הרלוונטי
2. לחץ על כפתור 'שלם עכשיו'
3. מלא את פרטי החשבון בבנק (מספר חשבון, סניף, בנק)
4. בחר את סוג התשלום (הון עצמי או משכנתא)
5. הגדר מורשה חתימה והעלה תעודת זהות
6. חתום דיגיטלית להשלמת התהליך

כל התשלומים מאובטחים ומוצפנים."""

    if any(word in message_lower for word in ["בנק", "חשבון", "סניף"]):
        return """למילוי פרטי חשבון הבנק:
- בחר את הבנק שלך מהרשימה הנפתחת
- הזן את מספר החשבון (ללא מקפים)
- הזן את מספר הסניף
- וודא שהפרטים נכונים לפני המשך התהליך

המערכת תומכת בכל הבנקים הגדולים בישראל."""

    if any(word in message_lower for word in ["מורשה חתימה", "חתימה", "זהות", "העלאה"]):
        return """להגדרת מורשה חתימה:
1. בחר את מספר מורשי החתימה הנדרשים
2. מלא את הפרטים האישיים של מורשה החתימה
3. העלה תמונה של תעודת הזהות (צילום ברור)
4. חתום באזור החתימה הדיגיטלית

וודא שתעודת הזהות ברורה וקריאה לאישור מהיר."""

    if any(word in message_lower for word in ["בעיה", "שגיאה", "לא עובד", "תקלה"]):
        return """אם אתה נתקל בבעיות טכניות:
1. רענן את הדף ונסה שוב
2. וודא שהחיבור לאינטרנט יציב
3. נסה להתחבר מדפדפן אחר
4. נקה את המטמון והעוגיות

אם הבעיה נמשכת, צור קשר עם התמיכה הטכנית."""

    if any(word in message_lower for word in ["תודה", "תודה רבה", "אסור"]):
        return "בשמחה לעזור! אם יש לך שאלות נוספות על תהליך התשלום או המערכת, אני כאן בשבילך."

    log_unknown_question(user_message)

    return """מצטער, אני לא יכול לענות על השאלה הזו כרגע. אני רושם את השאלה שלך כדי שנוכל לשפר את השירות.

אני כאן לעזור לך עם מערכת HomePay לתשלום שוברי חוק מכר.
אני יכול לעזור עם:
• תהליך ההתחברות למערכת
• ביצוע תשלומים ומילוי פרטי בנק
• הגדרת מורשה חתימה והעלאת מסמכים
• פתרון בעיות טכניות

לקבלת מענה אנושי, פנה לכתובת: info@homepay.co.il"""

@app.route('/api/get_knowledge', methods=['GET'])
def get_knowledge():
    """Get current knowledge base"""
    try:
        kb = load_knowledge_base()
        return jsonify({"qa_pairs": kb.get('qa_pairs', [])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/get_instructions', methods=['GET'])
def get_instructions():
    """Get current model instructions"""
    try:
        instructions = load_model_instructions()
        return jsonify({"instructions": instructions})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/update_instructions', methods=['POST'])
def update_instructions():
    """Update model instructions"""
    try:
        data = request.get_json()
        instructions = data.get('instructions', '')

        if not instructions.strip():
            return jsonify({"error": "הנחיות לא יכולות להיות ריקות"}), 400

        backup_timestamp = create_backup()
        if not backup_timestamp:
            app.logger.warning("Failed to create backup, proceeding with update")

        instructions_data = {
            "instructions": instructions,
            "last_updated": datetime.now().isoformat(),
            "version": "1.0"
        }

        with open(MODEL_INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions_data, f, ensure_ascii=False, indent=2)

        app.logger.info("Model instructions updated successfully")
        return jsonify({"success": True, "backup": backup_timestamp})

    except Exception as e:
        app.logger.error(f"Failed to update instructions: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/add_knowledge', methods=['POST'])
def add_knowledge():
    """Add new knowledge base item"""
    try:
        data = request.get_json()
        question = data.get('question', '').strip()
        answer = data.get('answer', '').strip()

        if not question or not answer:
            return jsonify({"error": "שאלה ותשובה חובה"}), 400

        backup_timestamp = create_backup()
        if not backup_timestamp:
            app.logger.warning("Failed to create backup, proceeding with update")

        kb = load_knowledge_base()

        keywords = [word.strip() for word in question.split() if len(word.strip()) > 2]

        new_item = {
            "keywords": keywords,
            "question": question,
            "answer": answer
        }

        kb['qa_pairs'].append(new_item)

        with open(KNOWLEDGE_BASE_FILE, 'w', encoding='utf-8') as f:
            json.dump(kb, f, ensure_ascii=False, indent=2)

        app.logger.info(f"Added new knowledge item: {question[:50]}...")
        return jsonify({"success": True, "backup": backup_timestamp})

    except Exception as e:
        app.logger.error(f"Failed to add knowledge item: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/delete_knowledge', methods=['POST'])
def delete_knowledge():
    """Delete knowledge base item by index"""
    try:
        data = request.get_json()
        index = data.get('index')

        if index is None or not isinstance(index, int):
            return jsonify({"error": "אינדקס לא תקין"}), 400

        backup_timestamp = create_backup()
        if not backup_timestamp:
            app.logger.warning("Failed to create backup, proceeding with update")

        kb = load_knowledge_base()
        qa_pairs = kb.get('qa_pairs', [])

        if index < 0 or index >= len(qa_pairs):
            return jsonify({"error": "אינדקס מחוץ לטווח"}), 400

        removed_item = qa_pairs.pop(index)

        with open(KNOWLEDGE_BASE_FILE, 'w', encoding='utf-8') as f:
            json.dump(kb, f, ensure_ascii=False, indent=2)

        app.logger.info(f"Deleted knowledge item: {removed_item.get('question', '')[:50]}...")
        return jsonify({"success": True, "backup": backup_timestamp})

    except Exception as e:
        app.logger.error(f"Failed to delete knowledge item: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/create_backup', methods=['POST'])
def create_backup_endpoint():
    """Create manual backup"""
    try:
        backup_timestamp = create_backup()
        if backup_timestamp:
            return jsonify({"success": True, "backup": backup_timestamp})
        else:
            return jsonify({"error": "יצירת גיבוי נכשלה"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/get_backups', methods=['GET'])
def get_backups():
    """Get list of available backups"""
    try:
        if not os.path.exists(BACKUP_DIR):
            return jsonify({"backups": []})

        backups = []
        for filename in os.listdir(BACKUP_DIR):
            if filename.endswith('.json'):
                filepath = os.path.join(BACKUP_DIR, filename)
                stat = os.stat(filepath)
                backups.append({
                    "name": filename,
                    "date": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    "size": stat.st_size
                })

        backups.sort(key=lambda x: x['date'], reverse=True)
        return jsonify({"backups": backups})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/restore_backup', methods=['POST'])
def restore_backup():
    """Restore from backup"""
    try:
        data = request.get_json()
        backup_name = data.get('backup_name', '')

        if not backup_name:
            return jsonify({"error": "שם גיבוי חובה"}), 400

        backup_path = os.path.join(BACKUP_DIR, backup_name)
        if not os.path.exists(backup_path):
            return jsonify({"error": "גיבוי לא נמצא"}), 404

        if 'knowledge_base' in backup_name:
            target_file = KNOWLEDGE_BASE_FILE
        elif 'model_instructions' in backup_name:
            target_file = MODEL_INSTRUCTIONS_FILE
        elif 'representative_settings' in backup_name:
            target_file = REPRESENTATIVE_SETTINGS_FILE
        else:
            return jsonify({"error": "סוג גיבוי לא מזוהה"}), 400

        current_backup = create_backup()

        shutil.copy2(backup_path, target_file)

        app.logger.info(f"Restored {target_file} from backup {backup_name}")
        return jsonify({"success": True, "current_backup": current_backup})

    except Exception as e:
        app.logger.error(f"Failed to restore backup: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/get_representative', methods=['GET'])
def get_representative():
    """Get current representative settings"""
    try:
        settings = load_representative_settings()
        return jsonify(settings)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/update_representative', methods=['POST'])
def update_representative():
    """Update representative settings"""
    try:
        data = request.get_json()
        name = data.get('name', 'סוכן HomePay')
        gender = data.get('gender', 'male')
        communication_style = data.get('communication_style', 'young_friendly')

        if gender == 'female':
            profile_picture = 'assets/profiles/Fagent_profile.jpg'
        else:  # male
            profile_picture = 'assets/profiles/Magent_profile.jpg'

        if gender not in ['male', 'female']:
            return jsonify({"error": "מין לא תקין"}), 400

        if communication_style not in ['young_friendly', 'formal_professional']:
            return jsonify({"error": "סגנון תקשורת לא תקין"}), 400

        if not name or len(name.strip()) == 0:
            return jsonify({"error": "שם הסוכן לא יכול להיות רק"}), 400

        backup_timestamp = create_backup()
        if not backup_timestamp:
            app.logger.warning("Failed to create backup, proceeding with update")

        settings_data = {
            "name": name.strip(),
            "gender": gender,
            "communication_style": communication_style,
            "profile_picture": profile_picture,
            "last_updated": datetime.now().isoformat(),
            "version": "1.0"
        }

        with open(REPRESENTATIVE_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_data, f, ensure_ascii=False, indent=2)

        app.logger.info(f"Representative settings updated: {name}, {gender}, {communication_style}, profile: {profile_picture}")
        return jsonify({"success": True, "backup": backup_timestamp, "profile_picture": profile_picture})

    except Exception as e:
        app.logger.error(f"Failed to update representative settings: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/get_unknown_questions', methods=['GET'])
def get_unknown_questions():
    """Get list of unknown questions"""
    try:
        unknown_questions_file = os.path.join(os.path.dirname(__file__), 'unknown_questions.json')

        if not os.path.exists(unknown_questions_file):
            return jsonify([])

        with open(unknown_questions_file, 'r', encoding='utf-8') as f:
            unknown_questions = json.load(f)

        return jsonify(unknown_questions)

    except Exception as e:
        app.logger.error(f"Failed to get unknown questions: {e}")
        return jsonify({"error": "שגיאה בטעינת שאלות לא ידועות"}), 500

@app.route('/api/mark_question_resolved', methods=['POST'])
def mark_question_resolved():
    """Mark an unknown question as resolved"""
    try:
        data = request.get_json()
        question_id = data.get('id')

        if not question_id:
            return jsonify({"error": "מזהה שאלה חסר"}), 400

        unknown_questions_file = os.path.join(os.path.dirname(__file__), 'unknown_questions.json')

        if not os.path.exists(unknown_questions_file):
            return jsonify({"error": "קובץ שאלות לא נמצא"}), 404

        with open(unknown_questions_file, 'r', encoding='utf-8') as f:
            unknown_questions = json.load(f)

        question_found = False
        for question in unknown_questions:
            if question.get('id') == question_id:
                question['resolved'] = True
                question['resolved_at'] = datetime.now().isoformat()
                question_found = True
                break

        if not question_found:
            return jsonify({"error": "שאלה לא נמצאה"}), 404

        with open(unknown_questions_file, 'w', encoding='utf-8') as f:
            json.dump(unknown_questions, f, ensure_ascii=False, indent=2)

        app.logger.info(f"Marked question {question_id} as resolved")
        return jsonify({"success": True})

    except Exception as e:
        app.logger.error(f"Failed to mark question as resolved: {e}")
        return jsonify({"error": "שגיאה בעדכון סטטוס שאלה"}), 500

@app.route('/api/upload_profile_picture', methods=['POST'])
def upload_profile_picture():
    """Upload profile picture for the agent"""
    try:
        if 'profile_picture' not in request.files:
            return jsonify({"error": "לא נבחר קובץ"}), 400

        file = request.files['profile_picture']
        if file.filename == '':
            return jsonify({"error": "לא נבחר קובץ"}), 400

        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        file_extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        if file_extension not in allowed_extensions:
            return jsonify({"error": "סוג קובץ לא נתמך. השתמש ב-PNG, JPG, JPEG, GIF או WebP"}), 400

        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to beginning
        if file_size > 5 * 1024 * 1024:
            return jsonify({"error": "גודל הקובץ חייב להיות קטן מ-5MB"}), 400

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"profile_{timestamp}.{file_extension}"

        # Save to assets directory
        assets_dir = os.path.join(os.path.dirname(__file__), 'assets')
        if not os.path.exists(assets_dir):
            os.makedirs(assets_dir)

        file_path = os.path.join(assets_dir, filename)
        file.save(file_path)

        app.logger.info(f"Profile picture uploaded: {filename}")
        return jsonify({"success": True, "filename": f"assets/{filename}"})

    except Exception as e:
        app.logger.error(f"Failed to upload profile picture: {e}")
        return jsonify({"error": "שגיאה בהעלאת התמונה"}), 500

@app.route('/api/send_verification_code', methods=['POST'])
def send_verification_code():
    """Send verification code to phone (simulated)"""
    try:
        data = request.get_json()
        phone = data.get('phone', '').strip()

        if not phone:
            return jsonify({'success': False, 'message': 'מספר טלפון נדרש'}), 400

        session['pending_phone'] = phone
        session['verification_code'] = '3110'  # Fixed code as requested

        app.logger.info(f"Verification code requested for phone: {phone}")
        return jsonify({
            'success': True,
            'message': 'קוד אימות נשלח בהצלחה'
        })

    except Exception as e:
        app.logger.error(f"Error sending verification code: {str(e)}")
        return jsonify({'success': False, 'message': 'שגיאה בשליחת קוד אימות'}), 500

@app.route('/api/verify_phone', methods=['POST'])
def verify_phone():
    """Verify phone number with code"""
    try:
        data = request.get_json()
        phone = data.get('phone', '').strip()
        code = data.get('code', '').strip()

        if not phone or not code:
            return jsonify({'success': False, 'message': 'מספר טלפון וקוד נדרשים'}), 400

        if (session.get('pending_phone') == phone and
            session.get('verification_code') == code):

            session['verified_phone'] = phone
            session.pop('pending_phone', None)
            session.pop('verification_code', None)

            app.logger.info(f"Phone verified successfully: {phone}")
            return jsonify({
                'success': True,
                'message': 'אימות הטלפון בוצע בהצלחה'
            })
        else:
            app.logger.warning(f"Failed phone verification for: {phone}")
            return jsonify({'success': False, 'message': 'קוד אימות שגוי'}), 401

    except Exception as e:
        app.logger.error(f"Error verifying phone: {str(e)}")
        return jsonify({'success': False, 'message': 'שגיאה באימות הטלפון'}), 500

@app.route('/api/log_chat_transcript', methods=['POST'])
def log_chat_transcript():
    """Log chat transcript when user contacts human representative"""
    try:
        data = request.get_json()
        transcript = data.get('transcript', '')
        timestamp = data.get('timestamp', datetime.now().isoformat())
        phone = data.get('phone', session.get('verified_phone', 'Unknown'))

        transcripts_dir = 'chat_transcripts'
        if not os.path.exists(transcripts_dir):
            os.makedirs(transcripts_dir)

        # Generate filename with timestamp and phone
        safe_phone = phone.replace('-', '').replace(' ', '').replace('+', '') if phone != 'Unknown' else 'Unknown'
        filename = f"chat_transcript_{safe_phone}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = os.path.join(transcripts_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"Chat Transcript - {timestamp}\n")
            if phone != 'Unknown':
                f.write(f"Phone: {phone}\n")
            f.write("=" * 50 + "\n\n")
            f.write(transcript)

        app.logger.info(f"Chat transcript logged: {filename} for phone: {phone}")
        return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        app.logger.error(f"Failed to log chat transcript: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # When running locally for development:
    # 1. Make sure Flask is installed: pip install Flask Flask-CORS
    # 2. Run this script: python app.py
    # 3. The Flask server will start (usually on http://127.0.0.1:5000).
    # 4. Ensure your HTML guide (e.g., homepay_guide_developer.html) is also served,
    #    perhaps using Python's http.server on a DIFFERENT port (e.g., 8000) in the directory
    #    containing all HTML, XML, CSS, and image files.
    #    Open http://localhost:8000/homepay_guide_developer.html in your browser,
    #    then click the "תמיכה עם סוכן AI" link which should go to http://localhost:8000/ai_support_agent.html.
    #    The JavaScript in ai_support_agent.html will then make requests to this Flask server (http://localhost:5000/api/chat).

    # For a more integrated setup where Flask serves everything:
    # You would typically configure Flask to serve static files (HTML, CSS, JS, images, XML)
    # from a 'static' folder and templates from a 'templates' folder.
    # This example keeps the Python server minimal and focused on the API.

    app.run(debug=False, host='0.0.0.0', port=5000) # Runs on all interfaces for production
    # Use debug=False in a production environment

# Instructions for running:
# 1. Save this file as app.py in your project root.
# 2. Install Flask and Flask-CORS:
#    pip install Flask Flask-CORS
# 3. Run the server:
#    python app.py
# 4. Serve your HTML/XML/Image files using another local server (e.g., `python -m http.server 8000` in the same directory)
#    or integrate static file serving into Flask for a more robust setup.
# 5. Access ai_support_agent.html through the server that serves the HTML files (e.g., http://localhost:8000/ai_support_agent.html).
#    The chat should then communicate with this Flask app on port 5000.
