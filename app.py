import os
import sys
import json
import uuid
import base64
import requests
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
import PyPDF2
import docx

app = Flask(__name__)

# Configuration
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max
app.config['ALLOWED_EXTENSIONS'] = {
    'txt', 'pdf', 'docx', 'doc', 'md', 'csv', 'json', 'xml', 'yaml', 'yml',
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'tif', 'webp'
}

# Ollama configuration
OLLAMA_URL = "http://localhost:11434/api"
DEFAULT_MODEL = "qwen2.5-coder:14b"

# In-memory storage for sessions
doc_sessions = {}   # Document sessions
code_sessions = {}  # Code sessions

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'tif', 'webp'}


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def is_image_file(filepath):
    ext = filepath.rsplit('.', 1)[1].lower() if '.' in filepath else ''
    return ext in IMAGE_EXTENSIONS


def extract_text_from_file(filepath):
    ext = filepath.rsplit('.', 1)[1].lower() if '.' in filepath else ''
    try:
        if ext in ('txt', 'md', 'csv', 'json', 'xml', 'yaml', 'yml'):
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        elif ext == 'pdf':
            text = ""
            with open(filepath, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            return text
        elif ext in ('docx', 'doc'):
            doc = docx.Document(filepath)
            return "\n".join([para.text for para in doc.paragraphs])
        elif ext in IMAGE_EXTENSIONS:
            return None  # Will be handled by vision model
        else:
            return None
    except Exception as e:
        return f"Error extracting text: {str(e)}"


def call_ollama(messages, model=None, stream=False):
    model = model or DEFAULT_MODEL
    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": {"temperature": 0.2, "num_predict": 4096}
    }
    try:
        response = requests.post(
            f"{OLLAMA_URL}/chat", json=payload, timeout=180
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot connect to Ollama. Make sure Ollama is running"}
    except requests.exceptions.Timeout:
        return {"error": "Request timed out."}
    except Exception as e:
        return {"error": f"Ollama error: {str(e)}"}


def analyze_with_ollama(text, filename, model=None, content_type="document"):
    """Send text content to Ollama for initial analysis."""
    model = model or DEFAULT_MODEL
    max_chars = 15000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n...[truncated]"

    if content_type == "code":
        system_prompt = """You are a code analysis assistant. Analyze the provided code and provide:
1. The programming language and overall purpose
2. Key components (functions, classes, modules)
3. Notable patterns, potential issues, or improvements
4. How the code works at a high level
Be technical and precise. Respond in the user's language."""
        user_prompt = f"""Please analyze this code (filename: {filename}):
---
{text}
---"""
    else:
        system_prompt = """You are a document analysis assistant. Analyze the document and extract key information.
Summarize and highlight important points, data, and insights. Respond in the same language as the document."""
        user_prompt = f"""Please analyze this document (filename: {filename}):
---
{text}
---"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    return call_ollama(messages, model)


# ===================== DOCUMENT MODULE =====================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/models', methods=['GET'])
def list_models():
    try:
        response = requests.get(f"{OLLAMA_URL}/tags", timeout=10)
        response.raise_for_status()
        models_data = response.json()
        model_list = [m['name'] for m in models_data.get('models', [])]
        return jsonify({"models": model_list})
    except Exception:
        return jsonify({"models": [DEFAULT_MODEL]})


@app.route('/api/doc/upload', methods=['POST'])
def upload_document():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    model = request.form.get('model', DEFAULT_MODEL)
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not supported"}), 400

    filename = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(filepath)

    is_image = is_image_file(filepath)
    extracted_text = extract_text_from_file(filepath)

    # For images, use vision model directly
    if is_image:
        # Read and encode image as base64
        with open(filepath, 'rb') as img_file:
            base64_image = base64.b64encode(img_file.read()).decode('utf-8')

        # Detect if model is vision-capable
        vision_prompt = "Describe this image in detail. What do you see? What text or content is present?"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": vision_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ]
        result = call_ollama(messages, model)
        analysis_content = result.get('message', {}).get('content', '') if "error" not in result else None

        if "error" in result:
            # Fallback: try text-based analysis with any extracted text
            analysis_content = None

        session_id = uuid.uuid4().hex
        doc_sessions[session_id] = {
            "filename": filename, "filepath": filepath, "text": "[Image uploaded - analyzed via vision model]",
            "model": model, "file_type": "image", "conversation": [],
            "base64_image": base64_image
        }

        if analysis_content:
            doc_sessions[session_id]["conversation"].append({
                "role": "assistant", "content": f"[Image Analysis for: {filename}]\n\n{analysis_content}"
            })
            return jsonify({
                "session_id": session_id, "filename": filename, "file_type": "image",
                "analysis": analysis_content, "text_preview": ""
            })

        # If vision model failed, create session without analysis
        return jsonify({
            "session_id": session_id, "filename": filename, "file_type": "image",
            "analysis": "Image uploaded. You can ask questions about it.",
            "text_preview": ""
        })

    # Text-based files
    if extracted_text is None or extracted_text.startswith("Error"):
        os.remove(filepath)
        return jsonify({"error": extracted_text or "Could not extract text"}), 400

    session_id = uuid.uuid4().hex
    doc_sessions[session_id] = {
        "filename": filename, "filepath": filepath, "text": extracted_text,
        "model": model, "file_type": "document", "conversation": []
    }

    analysis = analyze_with_ollama(extracted_text, filename, model, "document")
    if "error" in analysis:
        return jsonify({"session_id": session_id, "filename": filename, "error": analysis["error"]}), 500

    analysis_content = analysis.get('message', {}).get('content', '')
    doc_sessions[session_id]["conversation"].append({
        "role": "assistant", "content": f"[Document Analysis for: {filename}]\n\n{analysis_content}"
    })

    return jsonify({
        "session_id": session_id, "filename": filename, "file_type": "document",
        "analysis": analysis_content, "text_preview": extracted_text[:500]
    })


@app.route('/api/doc/chat', methods=['POST'])
def chat_document():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON data"}), 400
    session_id = data.get('session_id')
    question = data.get('question', '').strip()
    if not session_id or session_id not in doc_sessions:
        return jsonify({"error": "Session not found. Upload a file first."}), 400
    if not question:
        return jsonify({"error": "Question cannot be empty"}), 400

    session = doc_sessions[session_id]
    model = data.get('model', session.get('model', DEFAULT_MODEL))
    is_image = session.get('file_type') == 'image'

    if is_image and session.get('base64_image'):
        # Send image + question to vision model
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{session['base64_image']}"}}
                ]
            }
        ]
        for msg in session["conversation"][-10:]:
            messages.append(msg)
    else:
        system_prompt = f"""You are a document analysis assistant. Answer based ONLY on the document.
Document: {session['filename']}
Content: {session['text']}"""
        messages = [{"role": "system", "content": system_prompt}]
        for msg in session["conversation"][-10:]:
            messages.append(msg)
        messages.append({"role": "user", "content": question})

    result = call_ollama(messages, model)
    if "error" in result:
        return jsonify({"error": result["error"]}), 500

    answer = result.get('message', {}).get('content', '')
    session["conversation"].append({"role": "user", "content": question})
    session["conversation"].append({"role": "assistant", "content": answer})

    return jsonify({"answer": answer})


@app.route('/api/doc/session/<session_id>/clear', methods=['POST'])
def clear_doc_session(session_id):
    if session_id not in doc_sessions:
        return jsonify({"error": "Session not found"}), 404
    doc_sessions[session_id]["conversation"] = []
    return jsonify({"success": True})


# ===================== CODE MODULE =====================

@app.route('/api/code/analyze', methods=['POST'])
def analyze_code():
    data = request.json
    if not data or 'code' not in data:
        return jsonify({"error": "No code provided"}), 400

    code = data['code'].strip()
    if not code:
        return jsonify({"error": "Code cannot be empty"}), 400

    language = data.get('language', 'auto-detect')
    model = data.get('model', DEFAULT_MODEL)

    session_id = uuid.uuid4().hex
    code_sessions[session_id] = {
        "code": code,
        "language": language,
        "model": model,
        "conversation": []
    }

    analysis = analyze_with_ollama(code, f"code.{language}", model, "code")
    if "error" in analysis:
        return jsonify({"session_id": session_id, "error": analysis["error"]}), 500

    analysis_content = analysis.get('message', {}).get('content', '')
    code_sessions[session_id]["conversation"].append({
        "role": "assistant",
        "content": f"[Code Analysis]\n\n{analysis_content}"
    })

    return jsonify({
        "session_id": session_id,
        "language": language,
        "analysis": analysis_content,
        "code_preview": code[:500]
    })


@app.route('/api/code/chat', methods=['POST'])
def chat_code():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON data"}), 400
    session_id = data.get('session_id')
    question = data.get('question', '').strip()
    if not session_id or session_id not in code_sessions:
        return jsonify({"error": "Session not found. Analyze code first."}), 400
    if not question:
        return jsonify({"error": "Question cannot be empty"}), 400

    session = code_sessions[session_id]
    model = data.get('model', session.get('model', DEFAULT_MODEL))

    system_prompt = f"""You are a code analysis assistant. Answer based on the code provided.
Code language: {session['language']}
Code:
---
{session['code']}
---"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in session["conversation"][-10:]:
        messages.append(msg)
    messages.append({"role": "user", "content": question})

    result = call_ollama(messages, model)
    if "error" in result:
        return jsonify({"error": result["error"]}), 500

    answer = result.get('message', {}).get('content', '')
    session["conversation"].append({"role": "user", "content": question})
    session["conversation"].append({"role": "assistant", "content": answer})

    return jsonify({"answer": answer})


@app.route('/api/code/session/<session_id>/clear', methods=['POST'])
def clear_code_session(session_id):
    if session_id not in code_sessions:
        return jsonify({"error": "Session not found"}), 404
    code_sessions[session_id]["conversation"] = []
    return jsonify({"success": True})


if __name__ == '__main__':
    print("🚀 Starting AI Local Support")
    print("📁 Modules: Document Analysis + Code Analysis")
    print(f"🌐 Open http://127.0.0.1:5001")
    app.run(host='0.0.0.0', port=5001, debug=True)