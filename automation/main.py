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

# 🔑 API KEYS (Pastikan variable environment diset atau edit manual di sini)
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

# 🌐 DOMAIN SETUP
WEBSITE_URL = "https://fastplace.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

# Cek API Key
if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing! Set env var GROQ_API_KEY")
    # exit(1) # Uncomment jika ingin strict

# 🔥 AUTHOR BARU: Persona Expert Adventure (E-E-A-T Friendly)
AUTHOR_PROFILES = [
    "Leo 'The Ranger' (Certified Mountain Guide)", 
    "Sarah Wilds (Survival Instructor)",
    "Mike Overland (4x4 & Camping Expert)", 
    "Dr. Forest Green (Botanist & Hiker)",
    "Elena Summit (Alpinist & Gear Reviewer)"
]

# 📂 KATEGORI (Adventure Niche)
VALID_CATEGORIES = [
    "Hiking Guides", "Survival Skills", "Camping Hacks", 
    "Gear Reviews", "Ultralight Backpacking", "Outdoor Safety",
    "Adventure Travel", "Mountaineering"
]

# 📡 SUMBER RSS (Adventure & Outdoor News)
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

# Target per sumber (Total 5-8 artikel per run)
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
    memory[title] = f"/articles/{slug}/" 
    if len(memory) > 500: memory = dict(list(memory.items())[-500:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def fetch_rss_feed(url):
    """
    Mengambil RSS dengan Header Browser Lengkap (Anti-Block)
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml, */*'
    }
    
    try:
        print(f"      ... Menghubungi Server RSS...")
        response = requests.get(url, headers=headers, timeout=20)
        
        if response.status_code == 200:
            feed = feedparser.parse(response.content)
            if len(feed.entries) > 0:
                print(f"      ✅ Berhasil! Ditemukan {len(feed.entries)} artikel.")
                return feed
            else:
                print(f"      ⚠️ Status 200 OK, tapi RSS Kosong.")
                return None
        else:
            print(f"      ❌ Gagal: HTTP Status {response.status_code}")
            return None
            
    except Exception as e:
        print(f"      ❌ Error Koneksi: {e}")
        return None

def clean_ai_content(text):
    """
    🔥 FUNGSI PEMBERSIH AGRESIF (ANTI-AI PATTERN)
    Menghapus Intro/Outro basi, Conclusion, dan frase robotik.
    """
    if not text: return ""
    
    # 1. Hapus Markdown Code Blocks
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
    
    # 2. HAPUS HEADER AI (Introduction, Conclusion, dll)
    # Regex ini menghapus Header + Paragraf pendek di bawahnya jika itu cuma basa-basi
    patterns_to_remove = [
        r'^#+\s*Introduction.*?$',
        r'^#+\s*Conclusion.*?$',
        r'^#+\s*Summary.*?$',
        r'^#+\s*The Verdict.*?$',
        r'^#+\s*Final Thoughts.*?$',
        r'^#+\s*In Conclusion.*?$'
    ]
    
    for pattern in patterns_to_remove:
        text = re.sub(pattern, '', text, flags=re.MULTILINE | re.IGNORECASE)

    # 3. Hapus Frase Pembuka AI
    ai_phrases = [
        r'^Here is a comprehensive guide.*',
        r'^In this article, we will explore.*',
        r'^Welcome to the ultimate guide.*',
        r'^Let\'s dive in.*',
        r'^Certainly! Here is.*',
        r'^This guide will tell you everything.*'
    ]
    for phrase in ai_phrases:
        text = re.sub(phrase, '', text, flags=re.MULTILINE | re.IGNORECASE)

    # 4. Normalisasi Markdown Header
    text = text.replace("<h1>", "# ").replace("</h1>", "\n")
    text = text.replace("<h2>", "## ").replace("</h2>", "\n")
    text = text.replace("<h3>", "### ").replace("</h3>", "\n")
    
    return text.strip()

# ==========================================
# 📑 AUTO TOC (NAVIGASI)
# ==========================================
def generate_toc(content_body):
    toc_lines = ["**Table of Contents**\n"]
    headers = re.findall(r'^(#{2,3})\s+(.+)$', content_body, flags=re.MULTILINE)
    
    if not headers: return ""

    for level, title in headers:
        anchor = slugify(title)
        if level == "##":
            toc_lines.append(f"- [{title}](#{anchor})")
        elif level == "###":
            toc_lines.append(f"  - [{title}](#{anchor})")
    
    return "\n".join(toc_lines) + "\n\n---\n\n"

# ==========================================
# 🧠 SMART SILO LINKING
# ==========================================
def inject_links_into_body(content_body, current_title):
    memory = load_link_memory()
    items = list(memory.items())
    
    if not items: return content_body
    
    # Contextual Matching sederhana
    keywords = [w.lower() for w in current_title.split() if len(w) > 4]
    matches = []
    
    for title, url in items:
        if any(k in title.lower() for k in keywords):
            matches.append((title, url))
    
    if not matches:
        matches = random.sample(items, min(3, len(items)))
    else:
        matches = matches[:3]

    link_box = "\n\n> **🏕️ Read More Adventures:**\n"
    for title, url in matches:
        link_box += f"> - [{title}]({url})\n"
    link_box += "\n"

    # Sisipkan setelah paragraf ke-3 agar tidak mengganggu intro
    paragraphs = content_body.split('\n\n')
    if len(paragraphs) > 4:
        paragraphs.insert(3, link_box)
        return "\n\n".join(paragraphs)
    
    return content_body + link_box

# ==========================================
# 🚀 INDEXING FUNCTIONS
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
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json; charset=utf-8'}, timeout=10)
        print(f"      🚀 IndexNow Submitted")
    except Exception as e: print(f"      ⚠️ IndexNow Failed: {e}")

# ==========================================
# 🎨 IMAGE GENERATOR (Outdoor Style)
# ==========================================
def generate_outdoor_image(prompt, filename):
    output_path = f"{IMAGE_DIR}/{filename}"
    
    # 🔥 GAYA VISUAL: National Geographic Style
    forced_style = "National Geographic photography, cinematic 4k, epic mountain landscape, outdoor gear detail, golden hour lighting, hyper-realistic, sharp focus, 8k resolution"
    
    clean_prompt = prompt.replace("Guide", "").replace("Review", "").strip()
    final_prompt = f"{clean_prompt}, {forced_style}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print(f"      🎨 Generating Image: {clean_prompt[:30]}...")

    # 1. POLLINATIONS (Priority)
    try:
        seed = random.randint(1, 99999)
        poly_url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(final_prompt)}?width=1280&height=720&model=flux&seed={seed}&nologo=true"
        resp = requests.get(poly_url, headers=headers, timeout=25)
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img.save(output_path, "WEBP", quality=90)
            print("      ✅ Image Saved (Pollinations)")
            return f"/images/{filename}"
    except Exception: pass

    # 2. FLICKR (Fallback)
    try:
        flickr_url = f"https://loremflickr.com/1280/720/hiking,mountain,forest/all"
        resp = requests.get(flickr_url, headers=headers, timeout=20, allow_redirects=True)
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img.save(output_path, "WEBP", quality=90)
            print("      ✅ Image Saved (Fallback)")
            return f"/images/{filename}"
    except Exception: pass

    return "/images/default-adventure.webp"

# ==========================================
# 🧠 CONTENT ENGINE (ANTI-AI PATTERN)
# ==========================================
def get_groq_article_json(title, summary, author_name):
    # 🔥 SYSTEM PROMPT: DIRECT & HUMAN-LIKE (NO FLUFF)
    # Prompt ini memaksa AI untuk TIDAK menulis Introduction/Conclusion
    system_prompt = f"""
    You are {author_name}, a rugged, no-nonsense Outdoor Expert. 
    You are writing for 'FastPlace', a site for serious adventurers.
    
    RULE 1: START IMMEDIATELY. Do NOT use "Introduction", "In this guide", or "Welcome". 
    Start directly with the problem or the hook. (e.g., "Your boots are the only thing separating you from a broken ankle...")
    
    RULE 2: NO "CONCLUSION" HEADERS. Do not write "## Conclusion". Just end the article with a final pro-tip or a safety warning.
    
    RULE 3: STRUCTURE. Use these specific headers instead of generic ones:
    - Instead of "Introduction", use a Story Hook.
    - Instead of "Steps", use "The Protocol" or "Field Execution".
    - Instead of "Tools", use "Gear Loadout".
    - Instead of "Tips", use "Ranger Secrets".
    
    RULE 4: TONE. Be authoritative, slightly gritty, but educational. Use short paragraphs.
    
    OBJECTIVE: Turn the input topic into a 1500+ word deep-dive manual.
    
    OUTPUT JSON FORMAT:
    {{
        "title": "Clickworthy Title (No Clickbait, Just Value)",
        "description": "Meta description (150 chars)",
        "category": "One of: {', '.join(VALID_CATEGORIES)}",
        "main_keyword": "SEO Keyword",
        "tags": ["tag1", "tag2", "tag3"],
        "content_body": "Full markdown content (No Title H1)..."
    }}
    """
    
    # User prompt memaksa AI untuk "Pivot" dari berita ke Panduan
    user_prompt = f"""
    TOPIC: {title}
    CONTEXT: {summary}
    
    TASK: Write a Master-Level Guide based on this. 
    If it's about a new product, review it strictly.
    If it's news, pivot to "How this affects hikers".
    
    REMEMBER: NO INTRODUCTIONS. NO CONCLUSIONS. START NOW.
    """
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing (Direct-Mode 1500+ Words)...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7, # Sedikit lebih kreatif agar tidak kaku
                max_tokens=7000,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError:
            print("      ⚠️ Rate Limit Hit, switching key...")
            time.sleep(2)
        except Exception as e: 
            print(f"      ⚠️ Groq Error: {e}")
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🌲 FASTPLACE ADVENTURE ENGINE (ANTI-SPAM EDITION) STARTED")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Reading: {source_name}")
        feed = fetch_rss_feed(rss_url)
        if not feed: continue

        processed_count = 0
        
        for entry in feed.entries:
            if processed_count >= TARGET_PER_SOURCE:
                print(f"   🛑 Target reached for {source_name}")
                break
            
            clean_title = entry.title.split(" - ")[0]
            # Slug dari judul asli dulu
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"
            
            # Cek jika file sudah ada
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): 
                print(f"   ⏩ Skipped (Ada): {clean_title[:30]}...")
                continue
            
            print(f"   ⚡ Processing: {clean_title[:40]}...")
            
            author = random.choice(AUTHOR_PROFILES)
            raw_json = get_groq_article_json(clean_title, entry.summary, author)
            
            if not raw_json: continue
            try:
                data = json.loads(raw_json)
            except:
                print("      ❌ JSON Parse Error")
                continue

            # Update slug jika judul berubah drastis (agar URL relevan dengan konten How-To)
            new_slug = slugify(data['title'], max_length=60, word_boundary=True)
            if new_slug != slug:
                filename = f"{new_slug}.md"
                slug = new_slug

            # 1. Generate Image (Outdoor Style)
            image_prompt = data.get('main_keyword', clean_title)
            final_img_path = generate_outdoor_image(image_prompt, f"{slug}.webp")
            
            # 2. Clean Content (Hapus Intro Basi)
            clean_body = clean_ai_content(data['content_body'])
            
            # 3. Generate TOC + Links
            toc_content = generate_toc(clean_body)
            body_with_links = inject_links_into_body(clean_body, data['title'])
            
            # Gabungkan: TOC + Body
            final_body = toc_content + body_with_links
            
            # 4. Fallback Category
            if data.get('category') not in VALID_CATEGORIES:
                data['category'] = "Adventure Guides"

            # 5. Create Markdown File (Hugo Style)
            md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{data['category']}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{final_img_path}"
description: "{data['description'].replace('"', "'")}"
slug: "{slug}"
url: "/articles/{slug}/"
draft: false
weight: {random.randint(1, 10)}
---

{final_body}

---
*Disclaimer: Outdoor activities carry inherent risks. Always prepare adequately. Content generated for educational purposes.*
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            save_link_to_memory(data['title'], slug)
            
            full_url = f"{WEBSITE_URL}/articles/{slug}/"
            submit_to_indexnow(full_url)

            print(f"      ✅ Published: {slug}")
            processed_count += 1
            
            print("      💤 Sleeping for 60s...")
            time.sleep(60)

if __name__ == "__main__":
    main()
