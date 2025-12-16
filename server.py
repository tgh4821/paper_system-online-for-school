import os
import json
import time
import shutil
import threading
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup

# --- 1. 基础配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR)
CORS(app) 

DATA_FILE = os.path.join(BASE_DIR, 'data.json')

# 引入线程锁：防止多个管理员同时点击保存时互相踩踏数据
data_lock = threading.Lock()

# --- 2. 安全的数据读写函数 ---

def load_data_from_disk():
    """安全读取：带损坏备份机制"""
    if not os.path.exists(DATA_FILE):
        return []
        
    with data_lock:
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            # 发生 JSON 解析错误时，千万不要直接返回 [] 去覆盖它！
            print(f"\n[!!! 严重警告 !!!] 读取 data.json 失败: {e}")
            backup_name = os.path.join(BASE_DIR, f"data_corrupted_{int(time.time())}.json")
            try:
                shutil.copy(DATA_FILE, backup_name)
                print(f"[提示] 系统已自动将损坏的文件备份为: {backup_name}")
                print(f"[提示] 请不要慌张，你可以尝试用文本编辑器打开备份文件抢救数据。")
            except Exception as be:
                print(f"[错误] 自动备份失败: {be}")
            
            # 备份完成后再返回空列表，确保服务不会彻底崩溃
            return []

def save_data_to_disk(data):
    """安全写入：带原子替换机制"""
    temp_file = DATA_FILE + '.tmp'
    
    with data_lock:
        try:
            # 0. 每次保存前先备份当前 data.json（若存在）
            if os.path.exists(DATA_FILE):
                backup_name = os.path.join(BASE_DIR, f"data_backup_{int(time.time() * 1000)}.json")
                shutil.copy(DATA_FILE, backup_name)

            # 1. 先将数据完整写入一个临时文件
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 2. 写入成功且完整后，瞬间替换原文件 (原子操作，极难被 Ctrl+C 或 kill 破坏)
            os.replace(temp_file, DATA_FILE)
            return True, None
            
        except Exception as e:
            print(f"[错误] 数据写入磁盘时发生异常: {e}")
            # 如果写入临时文件时报错，原文件 DATA_FILE 不会受到任何影响
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass
            return False, str(e)

# --- 3. 页面与静态文件路由 ---

@app.route('/')
def index_page():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory(BASE_DIR, filename)

# --- 4. 数据 API 接口 ---

@app.route('/api/get_messages', methods=['GET'])
def api_get_messages():
    data = load_data_from_disk()
    return jsonify(data)

@app.route('/api/save_messages', methods=['POST'])
def api_save_messages():
    new_data = request.get_json(silent=True)

    # 1) 仅允许数组
    if not isinstance(new_data, list):
        return jsonify({"status": "error", "message": "请求数据必须为数组(list)"}), 400

    current_data = load_data_from_disk()

    # 2) 禁止用空数组覆盖非空旧数据
    if isinstance(current_data, list) and len(current_data) > 0 and len(new_data) == 0:
        print("[拦截] 检测到空数组覆盖非空数据，已拒绝本次保存。")
        return jsonify({"status": "blocked", "message": "禁止空数组覆盖非空数据"}), 409

    # 3) 每次保存先做时间戳备份（在 save_data_to_disk 内执行）
    ok, err = save_data_to_disk(new_data)
    if not ok:
        return jsonify({"status": "error", "message": f"保存失败: {err}"}), 500

    return jsonify({"status": "success", "count": len(new_data)})

# --- 5. 获取标题接口 ---

@app.route('/get_title', methods=['GET'])
def get_title():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    print(f"[-] 正在尝试获取标题: {url}") 

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        og_title = soup.find('meta', property='og:title')
        twitter_title = soup.find('meta', property='twitter:title')
        
        if og_title and og_title.get('content'):
            title = og_title.get('content')
        elif twitter_title and twitter_title.get('content'):
            title = twitter_title.get('content')
        elif soup.title:
            title = soup.title.string.strip()
        else:
            title = "未命名标题"

        print(f"[+] 获取成功: {title}")
        return jsonify({'title': title})

    except Exception as e:
        print(f"[!] 获取失败: {e}")
        return jsonify({'title': url})

if __name__ == '__main__':
    print("==================================================")
    print("  🚀 海大小报后端服务已启动 (带防丢失安全机制)  ")
    print("  🌐 请在浏览器访问 http://localhost:5000")
    print("==================================================")
    app.run(host='0.0.0.0', port=5000)