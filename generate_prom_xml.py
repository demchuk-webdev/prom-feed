import xml.etree.ElementTree as ET
import json
import os
import time
import urllib.request
import sys
import subprocess

try:
    from groq import Groq
except ImportError:
    print("Installing groq library...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "groq"])
    from groq import Groq

# Use GEMINI_API_KEY (from GitHub Action secrets) or GROQ_API_KEY (from .env)
api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GROQ_API_KEY')
if not api_key:
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('GROQ_API_KEY'):
                    api_key = line.split('=', 1)[1].strip()
                elif line.startswith('GEMINI_API_KEY') and not api_key:
                    api_key = line.split('=', 1)[1].strip()
    except Exception:
        pass

if not api_key:
    print("ERROR: API_KEY не найден!")
    exit(1)

client = Groq(api_key=api_key)

FEED_URL = 'https://smart-b2b.com.ua/ua/index.php?route=extension/feed/unixml/droplangua'
INPUT_XML = 'smart-b2b-feed.xml'
OUTPUT_XML = 'prom_import.xml'
DB_FILE = 'processed_db.json'
LIMIT = 20000

def calc_price(supplier_price):
    return round((supplier_price * 1.2 + 90) / 0.765)

print("Скачиваем свежий прайс поставщика...")
req = urllib.request.Request(FEED_URL, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req) as response, open(INPUT_XML, 'wb') as out_file:
    out_file.write(response.read())

if os.path.exists(DB_FILE):
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        db = json.load(f)
else:
    db = {}

print("Читаем XML поставщика...")
tree = ET.parse(INPUT_XML)
root = tree.getroot()
shop = root.find('shop')
offers = shop.find('offers')

out_root = ET.Element("yml_catalog", date=time.strftime("%Y-%m-%d %H:%M"))
out_shop = ET.SubElement(out_root, "shop")
out_categories = ET.SubElement(out_shop, "categories")

categories = shop.find('categories')
if categories is not None:
    for cat in categories:
        out_categories.append(cat)

out_offers = ET.SubElement(out_shop, "offers")
processed_count = 0

for offer in offers.findall('offer'):
    if processed_count >= LIMIT:
        break
        
    vendor_code_el = offer.find('vendorCode')
    if vendor_code_el is None:
        continue
    sku = vendor_code_el.text
    
    price_el = offer.find('price')
    if price_el is None:
        continue
    supplier_price = float(price_el.text)
    
    name_el = offer.find('name')
    desc_el = offer.find('description')
    
    if name_el is None or desc_el is None:
        continue
        
    orig_name = name_el.text
    orig_desc = desc_el.text
    
    if sku in db and 'keywords_ua' in db[sku] and 'keywords_ru' in db[sku]:
        new_name_ua = db[sku]['new_name_ua']
        new_desc_ua = db[sku]['new_desc_ua']
        new_name_ru = db[sku]['new_name_ru']
        new_desc_ru = db[sku]['new_desc_ru']
        new_keywords_ua = db[sku]['keywords_ua']
        new_keywords_ru = db[sku]['keywords_ru']
    else:
        print(f"Генерируем текст Groq (UA + RU) для: {sku}")
        prompt = f"""
Ты опытный маркетолог и SEO-специалист для маркетплейсов.
Твоя задача — сделать рерайт названия и описания товара, чтобы они были уникальными, продающими и привлекали покупателей. Также сгенерируй список релевантных поисковых запросов (ключевых слов) для этого товара, по которым покупатели ищут его на маркетплейсе (до 15 ключевых фраз через запятую).
Оригинальное название: {orig_name}
Оригинальное описание: {orig_desc}

Ты должен вернуть строго JSON-объект с плоской структурой и следующими ключами:
- new_title_ua: (название на украинском языке)
- new_description_ua: (описание на украинском в формате HTML с тегами <p>, <ul>, <li>, <strong>)
- new_title_ru: (название на русском языке)
- new_description_ru: (описание на русском в формате HTML с тегами <p>, <ul>, <li>, <strong>)
- keywords_ua: (строка поисковых запросов на украинском через запятую)
- keywords_ru: (строка поисковых запросов на русском через запятую)
"""
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model="llama-3.1-8b-instant",
                response_format={"type": "json_object"},
            )
            result_text = chat_completion.choices[0].message.content
            data = json.loads(result_text)
            
            # Universal parser for both flat and nested structures
            if 'ua' in data and isinstance(data['ua'], dict):
                new_name_ua = data['ua'].get('title', data['ua'].get('new_title_ua', orig_name))
                new_desc_ua = data['ua'].get('description', data['ua'].get('new_description_ua', orig_desc))
                new_keywords_ua = data['ua'].get('keywords', data['ua'].get('keywords_ua', ''))
            else:
                new_name_ua = data.get('new_title_ua', orig_name)
                new_desc_ua = data.get('new_description_ua', orig_desc)
                new_keywords_ua = data.get('keywords_ua', '')

            if 'ru' in data and isinstance(data['ru'], dict):
                new_name_ru = data['ru'].get('title', data['ru'].get('new_title_ru', orig_name))
                new_desc_ru = data['ru'].get('description', data['ru'].get('new_description_ru', orig_desc))
                new_keywords_ru = data['ru'].get('keywords', data['ru'].get('keywords_ru', ''))
            else:
                new_name_ru = data.get('new_title_ru', orig_name)
                new_desc_ru = data.get('new_description_ru', orig_desc)
                new_keywords_ru = data.get('keywords_ru', '')
                
            db[sku] = {
                'new_name_ua': new_name_ua,
                'new_desc_ua': new_desc_ua,
                'new_name_ru': new_name_ru,
                'new_desc_ru': new_desc_ru,
                'keywords_ua': new_keywords_ua,
                'keywords_ru': new_keywords_ru
            }
            time.sleep(3.0)
        except Exception as e:
            print(f"Ошибка Groq: {e}")
            new_name_ua = orig_name
            new_desc_ua = orig_desc
            new_name_ru = orig_name
            new_desc_ru = orig_desc
            new_keywords_ua = ""
            new_keywords_ru = ""

    retail_price = calc_price(supplier_price)
    
    out_offer = ET.SubElement(out_offers, "offer", id=offer.get('id'), available=offer.get('available'))
    
    ET.SubElement(out_offer, "name").text = new_name_ru
    ET.SubElement(out_offer, "name_ua").text = new_name_ua
    
    ET.SubElement(out_offer, "vendorCode").text = sku
    
    ET.SubElement(out_offer, "price").text = str(retail_price)
    ET.SubElement(out_offer, "currencyId").text = "UAH"
    
    cat_el = offer.find('categoryId')
    if cat_el is not None:
        ET.SubElement(out_offer, "categoryId").text = cat_el.text
        
    vendor_el = offer.find('vendor')
    if vendor_el is not None and vendor_el.text:
        vendor_text = vendor_el.text.strip()
        invalid_vendors = ["невідомий виробник", "неизвестный производитель", "unknown"]
        if vendor_text and vendor_text.lower() not in invalid_vendors:
            ET.SubElement(out_offer, "vendor").text = vendor_text
    
    for pic in offer.findall('picture')[:10]:
        ET.SubElement(out_offer, "picture").text = pic.text
        
    cdata_desc_ru = f"<![CDATA[{new_desc_ru}]]>".replace("<", "___LT___").replace(">", "___GT___")
    cdata_desc_ua = f"<![CDATA[{new_desc_ua}]]>".replace("<", "___LT___").replace(">", "___GT___")
    
    ET.SubElement(out_offer, "description").text = cdata_desc_ru
    ET.SubElement(out_offer, "description_ua").text = cdata_desc_ua
    
    if new_keywords_ru:
        ET.SubElement(out_offer, "keywords").text = new_keywords_ru
    if new_keywords_ua:
        ET.SubElement(out_offer, "keywords_ua").text = new_keywords_ua
    
    for param in offer.findall('param'):
        p = ET.SubElement(out_offer, "param", name=param.get('name'))
        p.text = param.text
        
    processed_count += 1

with open(DB_FILE, 'w', encoding='utf-8') as f:
    json.dump(db, f, ensure_ascii=False, indent=2)

xml_str = ET.tostring(out_root, encoding='utf-8').decode('utf-8')
xml_str = xml_str.replace("&lt;![CDATA[", "<![CDATA[").replace("]]&gt;", "]]>")
xml_str = xml_str.replace("___LT___", "<").replace("___GT___", ">")

with open(OUTPUT_XML, 'w', encoding='utf-8') as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write('<!DOCTYPE yml_catalog SYSTEM "shops.dtd">\n')
    f.write(xml_str)

print(f"\nГотово! Файл {OUTPUT_XML} успешно обновлен.")
