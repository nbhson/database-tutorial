import os
import sys
import json
import uuid
import requests
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
import PyPDF2
import docx

app = Flask(__name__)

# Configuration
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max
app.config['ALLOWED_EXTENSIONS'] = {'txt', 'pdf', 'docx', 'doc', 'md', 'csv', 'json', 'xml', 'yaml', 'yml'}

# Ollama configuration
OLLAMA_URL = "http://localhost:11434/api"
# You can change this to any model you have: qwen2.5-coder:7b, deepseek-r1:14b, etc.
DEFAULT_MODEL = "qwen2.5-coder:7b"

# In-memory storage for sessions
# In production, use a database
sessions = {}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def extract_text_from_file(filepath):
    """Extract text from uploaded file based on its extension."""
    ext = filepath.rsplit('.', 1)[1].lower() if '.' in filepath else ''
    
    try:
        if ext == 'txt' or ext == 'md' or ext == 'csv' or ext == 'json' or ext == 'xml' or ext == 'yaml' or ext == 'yml':
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        elif ext == 'pdf':
            text = ""
            with open(filepath, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            return text
        elif ext == 'docx' or ext == 'doc':
            doc = docx.Document(filepath)
            return "\n".join([para.text for para in doc.paragraphs])
        else:
            return None
    except Exception as e:
        return f"Error extracting text: {str(e)}"


def call_ollama(messages, model=None, stream=False):
    """Call Ollama API with messages."""
    model = model or DEFAULT_MODEL
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": {
            "temperature": 0.2,
            "num_predict": 4096
        }
    }
    
    try:
        response = requests.post(
            f"{OLLAMA_URL}/chat",
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot connect to Ollama. Make sure Ollama is running (ollama serve)"}
    except requests.exceptions.Timeout:
        return {"error": "Request timed out. The model may be too slow or not loaded."}
    except Exception as e:
        return {"error": f"Ollama error: {str(e)}"}


def analyze_document_with_ollama(text, filename, model=None):
    """Send document content to Ollama for initial analysis."""
    model = model or DEFAULT_MODEL
    
    # Truncate text if too long (context window limit)
    max_chars = 15000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n...[truncated: file too long]"
    
    system_prompt = """You are a document analysis assistant. Your task is to analyze the provided document and extract key information. 
After analyzing, summarize the document and highlight important points, topics, data, and insights.
Be thorough and organized in your analysis. Respond in the same language as the document."""
    
    user_prompt = f"""Please analyze the following document (filename: {filename}) and provide:
1. A brief summary of what this document is about
2. Key topics and main points
3. Important data, figures, or insights
4. Any notable conclusions or recommendations

Document content:
---
{text}
---"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    return call_ollama(messages, model)


# ===== API ROUTES =====

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/models', methods=['GET'])
def list_models():
    """List available Ollama models."""
    try:
        response = requests.get(f"{OLLAMA_URL}/tags", timeout=10)
        response.raise_for_status()
        models_data = response.json()
        model_list = [m['name'] for m in models_data.get('models', [])]
        return jsonify({"models": model_list})
    except Exception as e:
        # Return default models if Ollama not reachable
        return jsonify({"models": [DEFAULT_MODEL], "error": str(e)})


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Upload a file, extract text, and analyze with Ollama."""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    model = request.form.get('model', DEFAULT_MODEL)
    
    if not allowed_file(file.filename):
        return jsonify({
            "error": f"File type not allowed. Supported: {', '.join(app.config['ALLOWED_EXTENSIONS'])}"
        }), 400
    
    # Save file
    filename = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(filepath)
    
    # Extract text
    extracted_text = extract_text_from_file(filepath)
    if extracted_text is None:
        os.remove(filepath)
        return jsonify({"error": "Could not extract text from this file type"}), 400
    
    # Create session
    session_id = uuid.uuid4().hex
    sessions[session_id] = {
        "filename": filename,
        "filepath": filepath,
        "text": extracted_text,
        "model": model,
        "conversation": []
    }
    
    # Analyze document
    analysis = analyze_document_with_ollama(extracted_text, filename, model)
    
    if "error" in analysis:
        return jsonify({
            "session_id": session_id,
            "filename": filename,
            "error": analysis["error"],
            "text_preview": extracted_text[:500]
        }), 500
    
    # Store analysis in conversation history
    analysis_content = analysis.get('message', {}).get('content', 'No analysis generated.')
    sessions[session_id]["conversation"].append({
        "role": "assistant",
        "content": f"[Document Analysis for: {filename}]\n\n{analysis_content}"
    })
    
    return jsonify({
        "session_id": session_id,
        "filename": filename,
        "analysis": analysis_content,
        "text_preview": extracted_text[:500]
    })


@app.route('/api/chat', methods=['POST'])
def chat():
    """Chat with Ollama about the uploaded document."""
    data = request.json
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400
    
    session_id = data.get('session_id')
    question = data.get('question', '').strip()
    
    if not session_id or session_id not in sessions:
        return jsonify({"error": "Invalid or expired session. Please upload a file first."}), 400
    
    if not question:
        return jsonify({"error": "Question cannot be empty"}), 400
    
    session = sessions[session_id]
    model = data.get('model', session.get('model', DEFAULT_MODEL))
    
    # Build conversation context
    system_prompt = f"""You are a document analysis assistant. You have been given a document to analyze.
The user will ask questions about the document. Answer based ONLY on the document content.
If the question cannot be answered from the document, say so politely.
Be concise and accurate. Respond in the same language as the user's question.

Document filename: {session['filename']}
Document content:
---
{session['text']}
---"""
    
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add conversation history (last 10 messages for context)
    for msg in session["conversation"][-10:]:
        messages.append(msg)
    
    # Add user's question
    messages.append({"role": "user", "content": question})
    
    # Call Ollama
    result = call_ollama(messages, model)
    
    if "error" in result:
        return jsonify({"error": result["error"]}), 500
    
    answer = result.get('message', {}).get('content', 'No response generated.')
    
    # Store in conversation history
    session["conversation"].append({"role": "user", "content": question})
    session["conversation"].append({"role": "assistant", "content": answer})
    
    return jsonify({
        "answer": answer,
        "conversation_length": len(session["conversation"])
    })


@app.route('/api/session/<session_id>', methods=['GET'])
def get_session(session_id):
    """Get session info."""
    if session_id not in sessions:
        return jsonify({"error": "Session not found"}), 404
    
    session = sessions[session_id]
    return jsonify({
        "session_id": session_id,
        "filename": session["filename"],
        "model": session["model"],
        "conversation": session["conversation"],
        "text_preview": session["text"][:200]
    })


@app.route('/api/session/<session_id>/clear', methods=['POST'])
def clear_session(session_id):
    """Clear conversation history but keep document."""
    if session_id not in sessions:
        return jsonify({"error": "Session not found"}), 404
    
    sessions[session_id]["conversation"] = []
    return jsonify({"success": True})


if __name__ == '__main__':
    print("🚀 Starting Document Analysis WebUI")
    print(f"📁 Uploads directory: {os.path.abspath(app.config['UPLOAD_FOLDER'])}")
    print(f"🤖 Default model: {DEFAULT_MODEL}")
    print(f"🌐 Open http://127.0.0.1:5001 in your browser")
    app.run(host='0.0.0.0', port=5001, debug=True)
