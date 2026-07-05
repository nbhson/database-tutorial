# DocAnalyzer - Document Analysis WebUI

WebUI phân tích tài liệu sử dụng **Ollama** (AI local) cho phép upload file và đặt câu hỏi về nội dung tài liệu.

## 🚀 Tính năng

- 📄 **Upload file**: Hỗ trợ PDF, DOCX, TXT, MD, CSV, JSON, XML, YAML
- 🤖 **Phân tích tự động**: AI local (Ollama) phân tích nội dung file ngay sau khi upload
- 💬 **Chat với tài liệu**: Đặt câu hỏi về nội dung, AI trả lời dựa trên tài liệu
- 🎯 **Câu hỏi gợi ý**: Các câu hỏi mẫu nhanh (tóm tắt, điểm chính, kết luận)
- 🔄 **Đa model**: Chọn bất kỳ model Ollama nào đã cài
- 🎨 **Giao diện tối**: Dark mode, responsive, drag & drop upload

## 📋 Yêu cầu

- **Python 3.8+**
- **Ollama** (đã cài và chạy) - [ollama.ai](https://ollama.ai)
- **Model Ollama** (ví dụ: `qwen2.5-coder:7b`, `deepseek-r1:14b`, ...)

## ⚙️ Cài đặt

### 1. Clone project

```bash
git clone <your-repo-url>
cd analyze-documents
```

### 2. Cài đặt Python dependencies

```bash
pip3 install -r requirements.txt
```

### 3. Cài model Ollama (nếu chưa có)

```bash
# Liệt kê model đã cài
ollama list

# Cài model (ví dụ)
ollama pull qwen2.5-coder:7b
ollama pull deepseek-r1:14b
```

### 4. Chạy ứng dụng

```bash
python3 app.py
```

Mở trình duyệt tại: **http://127.0.0.1:5001**

## 🎮 Cách sử dụng

1. **Mở** http://127.0.0.1:5001
2. **Chọn model** AI từ dropdown (mặc định: `qwen2.5-coder:7b`)
3. **Upload file**: Kéo-thả hoặc click vào vùng upload
4. **Xem phân tích**: AI tự động phân tích và hiển thị kết quả
5. **Đặt câu hỏi**: Nhập câu hỏi về nội dung tài liệu
6. **Xóa session**: Click icon thùng rác để upload file mới

## 📁 Cấu trúc project

```
analyze-documents/
├── app.py                  # Backend Flask (API + Ollama integration)
├── requirements.txt        # Python dependencies
├── README.md               # Tài liệu hướng dẫn
├── uploads/                # Thư mục lưu file upload (tự động tạo)
├── templates/
│   └── index.html          # Giao diện chính (HTML + JS)
└── static/
    └── style.css           # CSS styling (dark theme)
```

## 🔌 API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/` | Trang chủ WebUI |
| GET | `/api/models` | Danh sách model Ollama |
| POST | `/api/upload` | Upload file + phân tích |
| POST | `/api/chat` | Chat về tài liệu |
| GET | `/api/session/<id>` | Lấy thông tin session |
| POST | `/api/session/<id>/clear` | Xóa lịch sử chat |

## 🛠 Công nghệ

- **Backend**: Python Flask
- **Frontend**: HTML, CSS, JavaScript (thuần)
- **AI**: Ollama (local LLM)
- **File processing**: PyPDF2, python-docx

## 📝 Ghi chú

- File upload tối đa **50MB**
- Nội dung file dài sẽ được cắt ngắn (15,000 ký tự) để phù hợp context window của model
- Dữ liệu session lưu trong RAM (mất khi restart server)
- Port mặc định là **5001** (tránh xung đột với AirPlay Receiver trên macOS)

## 🐳 Troubleshooting

**Port 5001 đã được sử dụng?**
```bash
# Kiểm tra process đang dùng port
lsof -i :5001

# Kill process
kill -9 <PID>
```

**Ollama không kết nối được?**
```bash
# Kiểm tra Ollama đang chạy
ollama list

# Khởi động Ollama nếu cần
ollama serve