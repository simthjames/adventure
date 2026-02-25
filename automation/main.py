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

# ==========================================
# ⚙️ CONFIGURATION: FASTPLACE.BIZ.ID
# ==========================================

GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://fastplace.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing! Set env var GROQ_API_KEY")
    exit(1)

# 🔥 PERSONA PENULIS
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

# 📈 SEED KEYWORDS
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

TARGET_ARTICLES = 1  

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

def optimize_seo_slug(text, main_keyword=None):
    """
    🔥 SMART SEO SLUG:
    1. Prioritaskan Main Keyword jika ada (karena itu inti SEO).
    2. Hapus Stop Words (kata sambung).
    3. Batasi maks 5 kata.
    """
    # List kata sambung bahasa Inggris yang tidak perlu ada di URL
    stop_words = [
        'a', 'an', 'the', 'and', 'but', 'or', 'for', 'nor', 'on', 'at', 'to', 'from', 'by', 
        'with', 'in', 'of', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'that', 
        'this', 'guide', 'review', 'best', 'top', 'ultimate', 'complete', 'how', 'tips'
    ]
    
    # Jika ada main_keyword, gunakan itu sebagai basis slug (Lebih SEO Friendly)
    source_text = main_keyword if main_keyword and len(main_keyword.split()) > 1 else text
    
    # Bersihkan text
    words = slugify(source_text).split('-')
    
    # Filter stop words
    clean_words = [w for w in words if w not in stop_words]
    
    # Jika setelah filter kosong (misal judulnya cuma "The Best Guide"), kembalikan ke original
    if not clean_words:
        clean_words = words
        
    # Batasi maksimal 5 kata agar URL pendek & tajam
    final_slug = "-".join(clean_words[:5])
    
    return final_slug

def fetch_trending_topics(keywords, max_results=3):
    print(f"      ... Menghubungi Google Trends...")
    topics = []
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
                # Ambil keyword yang spesifik (Long Tail) tapi populer
                if len(query.split()) > 2:
                    topics.append(query.title())
                    if len(topics) >= max_results: break
            
            if len(topics) > 0:
                print(f"      ✅ Ditemukan {len(topics)} topik trending.")
                return topics
        
        print("      ⚠️ Menggunakan Seed Keyword (Fallback).")
        return [f"{current_kw}"]
            
    except Exception as e:
        print(f"      ⚠️ GTrends Fallback: {e}")
        return [f"{random.choice(keywords)}"]

def clean_markdown_body(text):
    if not text: return ""
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
    
    # Hapus Header Basi
    patterns = [r'^#+\s*Introduction', r'^#+\s*Conclusion', r'^#+\s*Summary']
    for p in patterns:
        text = re.sub(p, '', text, flags=re.MULTILINE | re.IGNORECASE)

    # Fix Spacing Headers
    text = re.sub(r'([^\n])\n(#{2,4}\s)', r'\1\n\n\2', text)
    return text.strip()

# ==========================================
# 📑 NAVIGASI & LINKS
# ==========================================
def generate_toc(content_body):
    headers = re.findall(r'^(#{2,3})\s+(.+)$', content_body, flags=re.MULTILINE)
    if not headers: return "" 

    toc_lines = ["**Table of Contents**\n"]
    for level, title in headers:
        anchor = slugify(title)
        indent = "  " if level == "###" else ""
        toc_lines.append(f"{indent}- [{title}](#{anchor})")
    
    return "\n".join(toc_lines) + "\n\n---\n\n"

def inject_smart_links(content_body, current_title):
    memory = load_link_memory()
    if not memory: return content_body
    
    current_keywords = set(current_title.lower().split())
    relevant_links = []
    
    for title, url in memory.items():
        title_words = set(title.lower().split())
        common = current_keywords.intersection(title_words)
        common = [w for w in common if len(w) > 4] 
        if len(common) > 0:
            relevant_links.append((title, url))
    
    if not relevant_links:
        relevant_items = list(memory.items())
        final_links = random.sample(relevant_items, min(3, len(relevant_items)))
    else:
        final_links = relevant_links[:3]

    if not final_links: return content_body

    link_box = "\n\n> **🏕️ Recommended for You:**\n"
    for title, url in final_links:
        link_box += f"> - [{title}]({url})\n"
    link_box += "\n"

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

    try:
        seed = random.randint(1, 99999)
        poly_url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(final_prompt)}?width=1280&height=720&model=flux&seed={seed}&nologo=true"
        resp = requests.get(poly_url, headers=headers, timeout=30)
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img.save(output_path, "WEBP", quality=90)
            return f"/images/{filename}"
    except: pass
    
    return "/images/default-adventure.webp"

# ==========================================
# 🧠 AI ENGINE (RAW MARKDOWN MODE)
# ==========================================
def get_groq_article_markdown(keyword, author_name):
    current_time = datetime.now().strftime("%B %Y")
    
    # 🔥 PROMPT YANG DIPERBAIKI
    # Fokus: Output Markdown yang bersih & Keyword Density yang wajar
    system_prompt = f"""
    You are {author_name}, a world-class Outdoor Expert.
    Current Date: {current_time}.
    
    TASK: Write a High-Quality Guide about "{keyword}".
    
    OUTPUT FORMAT:
    You must output a VALID MARKDOWN file with a YAML Frontmatter block at the very top.
    
    Structure:
    ---
    title: "Viral Title (Use Numbers or 'How To')"
    description: "SEO description (max 150 chars)"
    category: "Hiking Guides"
    tags: ["tag1", "tag2"]
    main_keyword: "{keyword}"
    ---
    
    [CONTENT START]
    
    RULES:
    1. NO "Introduction" or "Conclusion" headers. Start with a Hook.
    2. Use H2 (##) and H3 (###) extensively.
    3. Include a "Gear Checklist" section.
    4. Mention "{current_time}" naturally in the text.
    5. Tone: Experienced, Safety-conscious, Helpful.
    """
    
    user_prompt = f"Topic: {keyword}\n\nWrite the article now."
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing Deep-Dive (Markdown Mode)...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.6,
                max_tokens=7500,
            )
            return completion.choices[0].message.content
        except RateLimitError:
            time.sleep(5)
        except Exception as e:
            print(f"      ⚠️ Error: {e}")
    return None

def parse_ai_response(raw_text):
    try:
        match = re.search(r'---\n(.*?)\n---', raw_text, re.DOTALL)
        if match:
            yaml_text = match.group(1)
            data = {}
            for line in yaml_text.split('\n'):
                if ':' in line:
                    key, val = line.split(':', 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key == 'tags':
                        clean_tags = val.replace('[', '').replace(']', '').replace('"', '').replace("'", "")
                        data['tags'] = [t.strip() for t in clean_tags.split(',')]
                    else:
                        data[key] = val
            content_body = raw_text.split('---', 2)[-1].strip()
            return data, content_body
        else:
            return None, None
    except Exception: return None, None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🌲 FASTPLACE PRO ENGINE STARTED")

    trending_topics = fetch_trending_topics(SEED_KEYWORDS, max_results=TARGET_ARTICLES)
    
    processed_count = 0
    
    for topic in trending_topics:
        if processed_count >= TARGET_ARTICLES: break
        
        clean_topic = topic.strip().title()
        
        # Cek Duplikasi Sederhana (Nama File)
        # Kita pakai slug sementara untuk cek file, tapi file asli nanti pakai Optimized Slug
        temp_slug_check = slugify(clean_topic)
        exists = False
        for f in os.listdir(CONTENT_DIR):
            if temp_slug_check in f: exists = True
        
        if exists:
            print(f"   ⏩ Skipped: {clean_topic}")
            continue
            
        print(f"\n   ⚡ Processing: {clean_topic}")
        
        author = random.choice(AUTHOR_PROFILES)
        
        # 1. Generate Raw Markdown
        raw_output = get_groq_article_markdown(clean_topic, author)
        if not raw_output: continue
        
        # 2. Parse YAML & Body
        meta_data, body_content = parse_ai_response(raw_output)
        if not meta_data or not body_content: continue
            
        # 3. Finalize Data
        title = meta_data.get('title', clean_topic)
        main_kw = meta_data.get('main_keyword', clean_topic)
        
        # 🔥 SLUG OPTIMIZATION: Short & SEO Friendly
        # Menggunakan Main Keyword sebagai basis slug, bukan Judul Panjang
        final_slug = optimize_seo_slug(title, main_keyword=main_kw)
        
        filename = f"{final_slug}.md"
        img_filename = f"{final_slug}.webp"
        
        # 4. Generate Assets
        img_path = generate_outdoor_image(main_kw, img_filename)
        clean_body = clean_markdown_body(body_content)
        final_body = generate_toc(clean_body) + inject_smart_links(clean_body, title)
        
        # Fallback Data
        cat = meta_data.get('category', "Adventure Guides")
        if cat not in VALID_CATEGORIES: cat = random.choice(VALID_CATEGORIES)
        
        # 5. Write File
        md = f"""---
title: "{title.replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{cat}"]
tags: {json.dumps(meta_data.get('tags', []))}
featured_image: "{img_path}"
description: "{meta_data.get('description', '').replace('"', "'")}"
slug: "{final_slug}"
url: "/articles/{final_slug}/"
draft: false
weight: {random.randint(1, 10)}
---

{final_body}

---
*Disclaimer: Content generated for educational purposes based on current trending topics.*
"""
        with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
            f.write(md)
            
        save_link_to_memory(title, final_slug)
        submit_to_indexnow(f"{WEBSITE_URL}/articles/{final_slug}/")
        
        print(f"      ✅ Published: {final_slug}")
        processed_count += 1
        
        print("      💤 Cooling down 60s...")
        time.sleep(60)

if __name__ == "__main__":
    main()
