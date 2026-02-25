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

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing! Set env var GROQ_API_KEY")
    exit(1)

# 🔥 PERSONA PENULIS (Expert Level)
AUTHOR_PROFILES = [
    "Leo 'The Ranger' (Certified Mountain Guide)", 
    "Sarah Wilds (Survival Instructor)",
    "Mike Overland (4x4 & Camping Expert)", 
    "Dr. Forest Green (Botanist & Hiker)",
    "Elena Summit (Alpinist & Gear Reviewer)"
]

# 📂 KATEGORI
VALID_CATEGORIES = [
    "Hiking Guides", "Survival Skills", "Camping Hacks", 
    "Gear Reviews", "Ultralight Backpacking", "Outdoor Safety",
    "Adventure Travel", "Mountaineering"
]

# 📈 SEED KEYWORDS (Pancingan untuk Google Trends)
# Kita gunakan topik 'Broad' agar AI bisa menulis panjang lebar (Evergreen)
SEED_KEYWORDS = [
    "Hiking gear checklist", "Camping survival tips", "Backpacking essentials", 
    "Wilderness first aid", "Best hiking boots guide", "Winter camping guide",
    "Ultralight backpacking tips", "Outdoor navigation skills", "Bushcraft shelter",
    "Trekking pole guide", "Tent maintenance tips", "Sleeping bag selection"
]

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"

# Target Artikel per Run
TARGET_ARTICLES = 1  # Fokus kualitas per run (Long Form butuh waktu generate lama)

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
    Mengambil 'Rising Queries' + Fallback Cerdas
    """
    print(f"      ... Menghubungi Google Trends...")
    topics = []
    
    # Random delay agar terlihat natural
    time.sleep(random.uniform(2, 5))
    
    try:
        pytrends = TrendReq(hl='en-US', tz=360, timeout=(10,25))
        current_kw = random.choice(keywords)
        print(f"      🔍 Menganalisa Tren: '{current_kw}'")
        
        pytrends.build_payload([current_kw], cat=0, timeframe='today 1-m', geo='US', gprop='')
        related = pytrends.related_queries()
        
        if current_kw in related and related[current_kw]['rising'] is not None:
            df_rising = related[current_kw]['rising']
            for index, row in df_rising.iterrows():
                query = row['query']
                if len(query.split()) > 3: # Ambil Long Tail Keyword
                    topics.append(query.title())
                    if len(topics) >= max_results: break
            
            if len(topics) > 0:
                print(f"      ✅ Ditemukan {len(topics)} topik trending.")
                return topics
            
        print("      ⚠️ Tidak ada lonjakan signifikan, menggunakan Seed Keyword dengan Tahun.")
        return [f"{current_kw} {datetime.now().year}"]
            
    except Exception as e:
        print(f"      ⚠️ GTrends Fallback: {e}")
        # Jika G-Trends error, gunakan Seed Keyword + Tahun agar tetap Fresh
        return [f"{random.choice(keywords)} {datetime.now().year}"]

def clean_ai_content(text):
    if not text: return ""
    
    # Hapus Markdown Code
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
    
    # Hapus Header Basi (Intro/Conclusion/Summary)
    patterns_to_remove = [
        r'^#+\s*Introduction.*?$', r'^#+\s*Conclusion.*?$', 
        r'^#+\s*Summary.*?$', r'^#+\s*The Verdict.*?$',
        r'^#+\s*Final Thoughts.*?$', r'^#+\s*In Conclusion.*?$'
    ]
    for pattern in patterns_to_remove:
        text = re.sub(pattern, '', text, flags=re.MULTILINE | re.IGNORECASE)

    # Hapus Frase Robot
    ai_phrases = [
        r'^Here is a comprehensive guide.*', r'^In this article.*',
        r'^Welcome to the ultimate guide.*', r'^Let\'s dive in.*'
    ]
    for phrase in ai_phrases:
        text = re.sub(phrase, '', text, flags=re.MULTILINE | re.IGNORECASE)

    # Normalisasi Header
    text = text.replace("<h1>", "# ").replace("</h1>", "\n")
    text = text.replace("<h2>", "## ").replace("</h2>", "\n")
    text = text.replace("<h3>", "### ").replace("</h3>", "\n")
    text = text.replace("<h4>", "#### ").replace("</h4>", "\n")
    
    return text.strip()

# ==========================================
# 📑 NAVIGASI & SMART SILO LINKING
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

def inject_smart_links(content_body, current_title):
    memory = load_link_memory()
    if not memory: return content_body
    
    # Pecah judul jadi kata kunci (misal: "Hiking Boots" -> ["hiking", "boots"])
    current_keywords = set(current_title.lower().split())
    
    relevant_links = []
    
    # Cari artikel lain yang punya kata kunci sama
    for title, url in memory.items():
        title_words = set(title.lower().split())
        # Jika ada irisan kata kunci (selain kata umum)
        common = current_keywords.intersection(title_words)
        # Filter kata umum
        common = [w for w in common if len(w) > 4] 
        
        if len(common) > 0:
            relevant_links.append((title, url))
    
    # Jika tidak ada yang relevan, ambil random
    if not relevant_links:
        relevant_items = list(memory.items())
        final_links = random.sample(relevant_items, min(3, len(relevant_items)))
    else:
        # Ambil max 3 link relevan
        final_links = relevant_links[:3]

    if not final_links: return content_body

    link_box = "\n\n> **🏕️ Recommended for You:**\n"
    for title, url in final_links:
        link_box += f"> - [{title}]({url})\n"
    link_box += "\n"

    # Sisip di tengah artikel (Paragraf ke-5)
    paragraphs = content_body.split('\n\n')
    if len(paragraphs) > 6:
        paragraphs.insert(5, link_box)
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
    
    headers = {"User-Agent": "Mozilla/5.0"}

    # 1. Pollinations
    try:
        seed = random.randint(1, 99999)
        poly_url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(final_prompt)}?width=1280&height=720&model=flux&seed={seed}&nologo=true"
        resp = requests.get(poly_url, headers=headers, timeout=30)
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img.save(output_path, "WEBP", quality=90)
            return f"/images/{filename}"
    except: pass
    
    # 2. Fallback
    try:
        flickr_url = f"https://loremflickr.com/1280/720/hiking,nature/all"
        resp = requests.get(flickr_url, headers=headers, timeout=20, allow_redirects=True)
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        img.save(output_path, "WEBP", quality=90)
        return f"/images/{filename}"
    except: return "/images/default-adventure.webp"

# ==========================================
# 🧠 AI ENGINE (DEEP DIVE 1500+ WORDS)
# ==========================================
def get_groq_article_json(keyword, author_name):
    
    current_time = datetime.now().strftime("%B %Y")
    
    # 🔥 SYSTEM PROMPT: THE MONSTER INSTRUCTION
    # Memaksa struktur H2 -> H3 -> H4 dan Panjang > 1500 Kata
    system_prompt = f"""
    You are {author_name}, a world-class Outdoor Expert & Instructor.
    Current Date: {current_time}.
    
    OBJECTIVE: Write a MASSIVE, DEFINITIVE GUIDE (Target: 1800+ Words) about: "{keyword}".
    
    CRITICAL RULES FOR "QUALITY & DEPTH":
    1. **NO FLUFF:** Do NOT write "Introduction", "Conclusion", or "Summary". Start immediately with a Story Hook or a Hard Fact.
    2. **DEEP HIERARCHY:** You MUST use H2, H3, and H4 to break down complex topics.
       - H2: Major Section (e.g., "The Layering System")
       - H3: Sub-Topic (e.g., "Base Layers: Merino vs Synthetic")
       - H4: Detail/Nuance (e.g., "Why 250gsm Merino is best for February")
    3. **FRESHNESS:** Mention that this guide is updated for the **{current_time}** season/standards.
    4. **FORMATTING:** Use Bullet points, Bold text for emphasis, and Numbered lists.
    
    REQUIRED SECTIONS (Use Creative Headers, not these exact words):
    - **The Hook:** Why this matters right now.
    - **The Gear Loadout:** Detailed equipment list (Use H3 for each item).
    - **Field Protocols:** Step-by-step execution (Use H3/H4 for steps).
    - **Safety & Risk Management:** Critical warnings.
    - **Pro Tips / Ranger Secrets:** Advanced advice.
    
    OUTPUT JSON:
    {{
        "title": "A Viral/Clickworthy Title (Include '{datetime.now().year}')",
        "description": "SEO description (160 chars)",
        "category": "One of: {', '.join(VALID_CATEGORIES)}",
        "main_keyword": "{keyword}",
        "tags": ["tag1", "tag2", "tag3", "tag4"],
        "content_body": "Full markdown content (No Title H1)..."
    }}
    """
    
    user_prompt = f"""
    TOPIC: {keyword}
    
    TASK: Write the most complete guide on the internet about this. 
    Go deep. Explain the 'WHY' and 'HOW'. 
    Make it actionable for {current_time}.
    """
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing Deep-Dive on '{keyword}'...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.6, # Agak rendah agar output panjang & stabil
                max_tokens=7500, # Max Output Groq
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError:
            print("      ⚠️ Rate Limit Hit, sleeping...")
            time.sleep(5)
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

    print("🌲 FASTPLACE 'EVERGREEN' ENGINE STARTED")

    # 1. Fetch Topic
    trending_topics = fetch_trending_topics(SEED_KEYWORDS, max_results=TARGET_ARTICLES)
    
    processed_count = 0
    
    for topic in trending_topics:
        if processed_count >= TARGET_ARTICLES: break
        
        # Format Topik
        clean_topic = topic.strip().title()
        slug = slugify(clean_topic, max_length=60)
        
        # Cek Duplikasi
        exists = False
        for f in os.listdir(CONTENT_DIR):
            if slug in f: exists = True
        
        if exists:
            print(f"   ⏩ Skipped (Exist): {clean_topic}")
            continue
            
        print(f"\n   ⚡ Processing: {clean_topic}")
        
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
        
        # Generate Assets
        img_path = generate_outdoor_image(data['main_keyword'], img_filename)
        clean_body = clean_ai_content(data['content_body'])
        
        # Inject TOC & Smart Links
        final_body = generate_toc(clean_body)
        final_body = inject_smart_links(final_body, data['title'])
        
        # Fallback Category
        cat = data.get('category', "Adventure Guides")
        if cat not in VALID_CATEGORIES: cat = random.choice(VALID_CATEGORIES)

        # Create Markdown
        md = f"""---
title: "{data['title'].replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{cat}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{img_path}"
description: "{data['description'].replace('"', "'")}"
slug: "{final_slug}"
url: "/articles/{final_slug}/"
draft: false
weight: {random.randint(1, 10)}
---

{final_body}

---
*Disclaimer: Content generated for educational purposes. Always prioritize safety in the outdoors.*
"""
        with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
            f.write(md)
            
        save_link_to_memory(data['title'], final_slug)
        submit_to_indexnow(f"{WEBSITE_URL}/articles/{final_slug}/")
        
        print(f"      ✅ Published: {final_slug}")
        processed_count += 1
        
        # Jeda lebih lama karena artikel panjang butuh resource
        print("      💤 Cooling down 60s...")
        time.sleep(60)

if __name__ == "__main__":
    main()
