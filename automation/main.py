import os
import json
import requests
import time
import re
import random
import warnings 
import string
import pandas as pd
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image
from groq import Groq, APIError, RateLimitError
from pytrends.request import TrendReq

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning)

# --- GOOGLE INDEXING LIBS (Optional) ---
try:
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

# ==========================================
# ⚙️ CONFIGURATION: FASTPLACE.BIZ.ID
# ==========================================

# 🔑 API KEYS
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

# 🌐 DOMAIN SETUP
WEBSITE_URL = "https://fastplace.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing! Set env var GROQ_API_KEY")
    exit(1)

# 🔥 PERSONA PENULIS (Adventure Expert)
AUTHOR_PROFILES = [
    "Leo 'The Ranger' (Certified Mountain Guide)", 
    "Sarah Wilds (Survival Instructor)",
    "Mike Overland (4x4 & Camping Expert)", 
    "Dr. Forest Green (Botanist & Hiker)",
    "Elena Summit (Alpinist & Gear Reviewer)"
]

# 📂 KATEGORI (Sesuai Sidebar)
VALID_CATEGORIES = [
    "Hiking Guides", "Survival Skills", "Camping Hacks", 
    "Gear Reviews", "Ultralight Backpacking", "Outdoor Safety",
    "Adventure Travel", "Mountaineering"
]

# 📈 SEED KEYWORDS (Pancingan untuk Google Trends)
SEED_KEYWORDS = [
    "Hiking gear 2024", "Best camping tents", "Survival kit checklist", 
    "Hiking boots reviews", "National Parks guide", "Backpacking food ideas",
    "Winter camping tips", "Glamping essentials", "Trekking poles",
    "Ultralight backpacking gear", "Bushcraft skills", "Climbing safety"
]

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"

# Target Artikel per Run
TARGET_ARTICLES = 2

# ==========================================
# 🧠 HELPER FUNCTIONS
# ==========================================
def load_link_memory():
    if not os.path.exists(MEMORY_FILE): return {}
    try:
        with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/articles/{slug}/" 
    if len(memory) > 500: memory = dict(list(memory.items())[-500:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def fetch_trending_topics(keywords, max_results=3):
    """
    Mengambil 'Rising Queries' (Topik Naik Daun) dari Google Trends
    """
    print(f"      ... Menghubungi Google Trends...")
    topics = []
    
    # Random Backoff untuk menghindari blokir Google
    time.sleep(random.uniform(2, 5))
    
    try:
        # Inisialisasi Pytrends
        pytrends = TrendReq(hl='en-US', tz=360, timeout=(10,25))
        
        # Ambil 1 Keyword Acak dari Seed agar variatif
        current_kw = random.choice(keywords)
        print(f"      🔍 Menganalisa Tren untuk: '{current_kw}'")
        
        # Build Payload (Data 30 hari terakhir)
        pytrends.build_payload([current_kw], cat=0, timeframe='today 1-m', geo='US', gprop='')
        
        # Ambil Related Queries
        related = pytrends.related_queries()
        
        if current_kw in related and related[current_kw]['rising'] is not None:
            df_rising = related[current_kw]['rising']
            
            # Ambil top queries yang relevan
            for index, row in df_rising.iterrows():
                query = row['query']
                # Filter query yang terlalu pendek
                if len(query.split()) > 2: 
                    topics.append(query.title())
                    if len(topics) >= max_results:
                        break
            
            if len(topics) > 0:
                print(f"      ✅ Ditemukan {len(topics)} topik trending: {topics}")
                return topics
            
        print("      ⚠️ Tidak ada data 'Rising' signifikan, menggunakan keyword asli.")
        return [current_kw]
            
    except Exception as e:
        print(f"      ⚠️ GTrends Error (Limit/Block): {e}")
        # Fallback ke keyword itu sendiri jika API gagal
        return [current_kw]

def clean_ai_content(text):
    """
    Membersihkan output AI dari basa-basi robot (Intro/Conclusion)
    """
    if not text: return ""
    
    # 1. Hapus Block Code Markdown
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
    
    # 2. HAPUS HEADER BASI
    patterns_to_remove = [
        r'^#+\s*Introduction.*?$', r'^#+\s*Conclusion.*?$', 
        r'^#+\s*Summary.*?$', r'^#+\s*The Verdict.*?$',
        r'^#+\s*Final Thoughts.*?$', r'^#+\s*In Conclusion.*?$'
    ]
    for pattern in patterns_to_remove:
        text = re.sub(pattern, '', text, flags=re.MULTILINE | re.IGNORECASE)

    # 3. Hapus Frase Robot
    ai_phrases = [
        r'^Here is a comprehensive guide.*', r'^In this article.*',
        r'^Welcome to the ultimate guide.*', r'^Let\'s dive in.*',
        r'^Certainly! Here is.*'
    ]
    for phrase in ai_phrases:
        text = re.sub(phrase, '', text, flags=re.MULTILINE | re.IGNORECASE)

    # 4. Normalisasi Markdown Header
    text = text.replace("<h1>", "# ").replace("</h1>", "\n")
    text = text.replace("<h2>", "## ").replace("</h2>", "\n")
    text = text.replace("<h3>", "### ").replace("</h3>", "\n")
    
    return text.strip()

# ==========================================
# 📑 NAVIGASI & LINKS
# ==========================================
def generate_toc(content_body):
    toc_lines = ["**Table of Contents**\n"]
    headers = re.findall(r'^(#{2,3})\s+(.+)$', content_body, flags=re.MULTILINE)
    if not headers: return ""
    for level, title in headers:
        anchor = slugify(title)
        indent = "  " if level == "###" else ""
        toc_lines.append(f"{indent}- [{title}](#{anchor})")
    return "\n".join(toc_lines) + "\n\n---\n\n"

def inject_links_into_body(content_body, current_title):
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return content_body
    
    # Ambil random link untuk variasi
    matches = random.sample(items, min(3, len(items)))
    
    link_box = "\n\n> **🏕️ Explore More Adventures:**\n"
    for title, url in matches:
        link_box += f"> - [{title}]({url})\n"
    link_box += "\n"

    # Sisip di paragraf ke-4
    paragraphs = content_body.split('\n\n')
    if len(paragraphs) > 4:
        paragraphs.insert(3, link_box)
        return "\n\n".join(paragraphs)
    return content_body + link_box

# ==========================================
# 🚀 INDEXING
# ==========================================
def submit_to_indexnow(url):
    try:
        endpoint = "https://api.indexnow.org/indexnow"
        host = "fastplace.biz.id"
        data = {
            "host": host, "key": INDEXNOW_KEY,
            "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt",
            "urlList": [url]
        }
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json'}, timeout=10)
        print(f"      🚀 IndexNow Submitted")
    except Exception: pass

# ==========================================
# 🎨 IMAGE GENERATOR
# ==========================================
def generate_outdoor_image(prompt, filename):
    output_path = f"{IMAGE_DIR}/{filename}"
    forced_style = "National Geographic photography, cinematic 4k, epic mountain landscape, outdoor gear detail, golden hour lighting, hyper-realistic, sharp focus, 8k resolution"
    
    clean_prompt = prompt.replace("Guide", "").replace("Review", "").strip()
    final_prompt = f"{clean_prompt}, {forced_style}"
    
    print(f"      🎨 Generating Image: {clean_prompt[:30]}...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # 1. Pollinations (Priority)
    try:
        seed = random.randint(1, 99999)
        poly_url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(final_prompt)}?width=1280&height=720&model=flux&seed={seed}&nologo=true"
        resp = requests.get(poly_url, headers=headers, timeout=30)
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img.save(output_path, "WEBP", quality=90)
            return f"/images/{filename}"
    except: pass
    
    # 2. Fallback Flickr
    try:
        flickr_url = f"https://loremflickr.com/1280/720/hiking,nature/all"
        resp = requests.get(flickr_url, headers=headers, timeout=20, allow_redirects=True)
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        img.save(output_path, "WEBP", quality=90)
        return f"/images/{filename}"
    except: return "/images/default-adventure.webp"

# ==========================================
# 🧠 AI ENGINE (GTRENDS MODE - DIRECT)
# ==========================================
def get_groq_article_json(keyword, author_name):
    # System Prompt Khusus Keyword (Bukan News)
    # Memaksa output langsung ke poin utama
    system_prompt = f"""
    You are {author_name}, an elite Outdoor Expert. 
    
    INPUT: You will receive a TRENDING KEYWORD.
    TASK: Create a Deep-Dive Guide (1800+ words) around this keyword.
    
    STYLE RULES:
    1. START IMMEDIATELY. NO "Introduction" headers. Start with a hook.
    2. NO "Conclusion" headers. End with a Pro Tip.
    3. Use Headers: "The Mission", "Gear Loadout", "Field Execution", "Pro Tips".
    4. Tone: Professional, Rugged, Educational.
    
    OUTPUT JSON:
    {{
        "title": "A Viral/Clickworthy Title based on '{keyword}'",
        "description": "SEO description (150 chars)",
        "category": "One of: {', '.join(VALID_CATEGORIES)}",
        "main_keyword": "{keyword}",
        "tags": ["tag1", "tag2", "tag3"],
        "content_body": "Full markdown content (No H1 Title)..."
    }}
    """
    
    user_prompt = f"KEYWORD: {keyword}\n\nWrite a comprehensive Master Guide about this topic."
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing about '{keyword}'...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=7000,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError:
            time.sleep(2)
        except Exception as e:
            print(f"      ⚠️ Error: {e}")
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🌲 FASTPLACE GTRENDS ENGINE STARTED")

    # 1. Fetch Trending Topics
    trending_topics = fetch_trending_topics(SEED_KEYWORDS, max_results=TARGET_ARTICLES)
    
    processed_count = 0
    
    for topic in trending_topics:
        if processed_count >= TARGET_ARTICLES: break
        
        # Bersihkan topic
        clean_topic = topic.strip()
        # Slug sementara untuk cek duplikasi
        temp_slug = slugify(clean_topic, max_length=60)
        
        # Cek apakah sudah pernah dibahas (berdasarkan file yang ada)
        # Scan folder content untuk kemiripan nama file
        exists = False
        for f_name in os.listdir(CONTENT_DIR):
            if temp_slug in f_name:
                exists = True
                break
        
        if exists:
            print(f"   ⏩ Skipped (Exist): {clean_topic}")
            continue
            
        print(f"\n   ⚡ Processing Trend: {clean_topic}")
        
        author = random.choice(AUTHOR_PROFILES)
        raw_json = get_groq_article_json(clean_topic, author)
        
        if not raw_json: continue
        try:
            data = json.loads(raw_json)
        except:
            print("      ❌ JSON Error")
            continue

        # Finalize
        final_slug = slugify(data['title'], max_length=60)
        filename = f"{final_slug}.md"
        img_filename = f"{final_slug}.webp"
        
        # Fallback Category
        cat = data.get('category', "Adventure Guides")
        if cat not in VALID_CATEGORIES: cat = random.choice(VALID_CATEGORIES)

        # Generate Assets
        img_path = generate_outdoor_image(data['main_keyword'], img_filename)
        clean_body = clean_ai_content(data['content_body'])
        final_body = generate_toc(clean_body) + inject_links_into_body(clean_body, data['title'])
        
        # Create File
        md = f"""---
title: "{data['title'].replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{cat}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{img_path}"
description: "{data['description'].replace('"', "'")}"
slug: "{final_slug}"
draft: false
weight: {random.randint(1, 10)}
---

{final_body}

---
*Disclaimer: Content generated for educational purposes based on current trending topics.*
"""
        with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
            f.write(md)
            
        save_link_to_memory(data['title'], final_slug)
        submit_to_indexnow(f"{WEBSITE_URL}/articles/{final_slug}/")
        
        print(f"      ✅ Published: {final_slug}")
        processed_count += 1
        
        print("      💤 Cooldown 60s...")
        time.sleep(60)

if __name__ == "__main__":
    main()
