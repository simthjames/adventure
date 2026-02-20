import os
import json
import requests
import feedparser
import time
import re
import random
import warnings 
import string
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image
from groq import Groq, APIError, RateLimitError

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

# 🔴 PENTING: MASUKKAN API KEY GROQ DI SINI (Bisa banyak, dipisah koma)
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "gsk_YOUR_KEY_1, gsk_YOUR_KEY_2") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

# 🌐 DOMAIN SETUP
WEBSITE_URL = "https://fastplace.biz.id" 
# Ganti dengan Key IndexNow Anda untuk fastplace.biz.id (generate di indexnow.org)
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS or "YOUR_KEY" in GROQ_API_KEYS[0]:
    print("⚠️ PERINGATAN: Groq API Key belum diisi dengan benar!")

# 🔥 PERSONA PENULIS (Expert Branding untuk FastPlace)
AUTHOR_PROFILES = [
    "Leo 'The Ranger' (Certified Mountain Guide)", 
    "Sarah Wilds (Survival Instructor)",
    "Mike Overland (4x4 & Camping Expert)", 
    "Dr. Forest Green (Botanist & Hiker)",
    "Elena Summit (Alpinist & Gear Reviewer)"
]

# 📂 KATEGORI (High CPC & AdSense Friendly)
VALID_CATEGORIES = [
    "Hiking Guides", "Survival Skills", "Camping Hacks", 
    "Gear Reviews", "Ultralight Backpacking", "Outdoor Safety",
    "Adventure Travel", "Mountaineering"
]

# 📡 SUMBER RSS BERKUALITAS (Adventure Niche)
RSS_SOURCES = {
    "Outside Online": "https://www.outsideonline.com/feed/",
    "The Trek": "https://thetrek.co/feed/", 
    "Backpacker": "https://www.backpacker.com/feed/",
    "Explorers Web": "https://explorersweb.com/feed/",
    "GearJunkie": "https://gearjunkie.com/feed"
}

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"

# Target Artikel Sekali Jalan (Jangan terlalu banyak agar aman)
TARGET_PER_SOURCE = 1

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
    # Simpan URL lengkap agar internal linking valid
    memory[title] = f"/articles/{slug}/" 
    if len(memory) > 500: memory = dict(list(memory.items())[-500:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def fetch_rss_feed(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml, */*'
    }
    try:
        print(f"      ... Mengambil RSS...")
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code == 200:
            feed = feedparser.parse(response.content)
            if len(feed.entries) > 0:
                print(f"      ✅ Berhasil! {len(feed.entries)} artikel ditemukan.")
                return feed
    except Exception as e:
        print(f"      ❌ Gagal Fetch RSS: {e}")
    return None

def clean_ai_content(text):
    if not text: return ""
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
    text = re.sub(r'^(Here is a|Sure|Certainly|In this guide).*?\n', '', text, flags=re.IGNORECASE)
    # Hapus H1 jika ada di dalam body (karena Hugo sudah handle title)
    text = re.sub(r'^#\s+.*?\n', '', text)
    return text.strip()

# ==========================================
# 📑 AUTO TOC & SMART INTERLINKING
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
    
    # Cari artikel terkait berdasarkan kata kunci sederhana
    keywords = [w.lower() for w in current_title.split() if len(w) > 4]
    matches = []
    
    for title, url in items:
        if any(k in title.lower() for k in keywords):
            matches.append((title, url))
            
    # Jika tidak ada yang match, ambil random (biar tetap ada link)
    if not matches: 
        matches = random.sample(items, min(3, len(items)))
    else: 
        matches = matches[:3]

    link_box = "\n\n> **🏕️ Explore More on FastPlace:**\n"
    for title, url in matches:
        link_box += f"> - [{title}]({url})\n"
    link_box += "\n"

    # Sisipkan link box setelah paragraf ke-4 atau ke-5
    parts = content_body.split('\n\n')
    if len(parts) > 4:
        parts.insert(3, link_box)
        return "\n\n".join(parts)
    
    return content_body + link_box

# ==========================================
# 🚀 INDEXING (Google & IndexNow)
# ==========================================
def submit_to_indexnow(url):
    try:
        endpoint = "https://api.indexnow.org/indexnow"
        host = "fastplace.biz.id"
        data = {
            "host": host,
            "key": INDEXNOW_KEY,
            "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt",
            "urlList": [url]
        }
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json; charset=utf-8'}, timeout=10)
        print(f"      🚀 IndexNow Submitted: {url}")
    except Exception as e: print(f"      ⚠️ IndexNow Failed: {e}")

# ==========================================
# 🎨 IMAGE GENERATOR (Nature/Adventure Style)
# ==========================================
def generate_outdoor_image(prompt, filename):
    output_path = f"{IMAGE_DIR}/{filename}"
    
    # Prompt Engineering untuk Gambar Realistis
    forced_style = "National Geographic photography, cinematic 4k, epic mountain landscape, outdoor gear detail, golden hour lighting, hyper-realistic, sharp focus, 8k resolution"
    
    clean_prompt = prompt.replace("Guide", "").replace("Review", "").strip()
    final_prompt = f"{clean_prompt}, {forced_style}"
    
    print(f"      🎨 Generating Image: {clean_prompt[:30]}...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # 1. Pollinations AI (Terbaik & Gratis)
    try:
        seed = random.randint(1, 99999)
        poly_url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(final_prompt)}?width=1280&height=720&model=flux&seed={seed}&nologo=true"
        resp = requests.get(poly_url, headers=headers, timeout=30)
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img.save(output_path, "WEBP", quality=85)
            print("      ✅ Image Saved (Pollinations)")
            return f"/images/{filename}"
    except Exception: pass
    
    # 2. Fallback: LoremFlickr
    try:
        flickr_url = "https://loremflickr.com/1280/720/hiking,mountain,forest/all"
        resp = requests.get(flickr_url, headers=headers, timeout=20)
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        img.save(output_path, "WEBP", quality=85)
        print("      ✅ Image Saved (Fallback)")
        return f"/images/{filename}"
    except: pass

    return "/images/default-adventure.webp"

# ==========================================
# 🧠 AI WRITER (Llama-3.3 70B - Deep Guide Mode)
# ==========================================
def get_groq_article_json(title, summary, author_name):
    # Prompt Super Detail untuk AdSense Approval
    system_prompt = f"""
    You are {author_name}, a professional Outdoor Guide writing for 'FastPlace Adventure'.
    
    OBJECTIVE: Write a COMPREHENSIVE, EVERGREEN GUIDE (Target: 1800+ words).
    
    INPUT: You will get a news headline or topic.
    TASK: Pivot this into a "How-to Guide" or "Ultimate Tutorial". Do NOT write news.
    
    MANDATORY STRUCTURE (Markdown):
    1. **Introduction**: Hook the reader immediately. Why is this topic crucial for adventurers?
    2. **Key Takeaways / At a Glance**: A small table or list summarizing the guide.
    3. **Gear Checklist** (If applicable): Bullet points of what is needed.
    4. **Safety & Preparation**: Crucial for outdoor niche.
    5. **Step-by-Step Guide** (The Meat): Use H3 (###) for steps. Be extremely detailed.
    6. **Pro Tips from the Field**: Secret tips only experts know.
    7. **Common Mistakes to Avoid**: Save the reader from failure.
    8. **FAQ**: 5 relevant questions and detailed answers.
    
    TONE: Helpful, Authoritative, Inspiring, Safety-Conscious.
    
    OUTPUT JSON FORMAT:
    {{
        "title": "A catchy, SEO-optimized title (e.g., 'The Ultimate Guide to...')",
        "description": "Meta description (150 chars) with keywords",
        "category": "One of: {', '.join(VALID_CATEGORIES)}",
        "main_keyword": "Primary SEO keyword",
        "tags": ["tag1", "tag2", "tag3"],
        "content_body": "Full markdown content (exclude title)..."
    }}
    """
    
    user_prompt = f"TOPIC: {title}\nCONTEXT: {summary}\n\nWrite the ultimate guide based on this."
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing (Deep Guide Mode)...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.6,
                max_tokens=6500, # Max token besar untuk artikel panjang
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError:
            print("      ⚠️ Limit reached, switching key...")
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
    
    print("🌲 FASTPLACE ADVENTURE ENGINE STARTED")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Scanning: {source_name}")
        feed = fetch_rss_feed(rss_url)
        if not feed: continue
        
        count = 0
        for entry in feed.entries:
            if count >= TARGET_PER_SOURCE: break
            
            clean_title = entry.title.split(" - ")[0]
            
            # Cek Duplikasi (Sederhana)
            slug_candidate = slugify(clean_title)
            if any(slug_candidate in f for f in os.listdir(CONTENT_DIR)):
                print(f"   ⏩ Skipped (Exist): {clean_title[:30]}...")
                continue
            
            print(f"   ⚡ Processing: {clean_title[:40]}...")
            
            author = random.choice(AUTHOR_PROFILES)
            ai_json = get_groq_article_json(clean_title, entry.summary, author)
            
            if not ai_json: continue
            
            try:
                data = json.loads(ai_json)
            except: 
                print("      ❌ JSON Error"); continue

            # Finalize Data
            final_slug = slugify(data['title'])
            filename = f"{final_slug}.md"
            img_filename = f"{final_slug}.webp"
            
            # Generate Image
            img_path = generate_outdoor_image(data['main_keyword'], img_filename)
            
            # Clean & Build Content
            body = clean_ai_content(data['content_body'])
            toc = generate_toc(body)
            body_linked = inject_links_into_body(body, data['title'])
            
            full_content = toc + body_linked
            
            # Fallback Category
            cat = data.get('category', "Adventure Guides")
            if cat not in VALID_CATEGORIES: cat = random.choice(VALID_CATEGORIES)

            # Create Frontmatter Markdown (Hugo Style)
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
---

{full_content}

---
*Disclaimer: Outdoor activities involve risk. Always prioritize safety and preparation. This guide is for educational purposes only.*
"""
            
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md)
            
            # Save to memory & IndexNow
            save_link_to_memory(data['title'], final_slug)
            submit_to_indexnow(f"{WEBSITE_URL}/articles/{final_slug}/")
            
            print(f"      ✅ Published: {filename}")
            count += 1
            
            print("      💤 Cooldown 30s...")
            time.sleep(30)

if __name__ == "__main__":
    main()