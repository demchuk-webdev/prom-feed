import xml.etree.ElementTree as ET
import json
import os
import time
import urllib.request
from google import genai
from google.genai import types

gemini_key = os.environ.get('GEMINI_API_KEY')
if not gemini_key:
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('GEMINI_API_KEY'):
                    gemini_key = line.split('=', 1)[1].strip()
    except Exception:
        pass

if not gemini_key:
    print("ERROR: GEMINI_API_KEY не найден!")
    exit(1)

client = genai.Client(api_key=gemini_key)

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
    
    if sku in db:
        new_name_ua = db[sku]['new_name_ua']
        new_desc_ua = db[sku]['new_desc_ua']
        new_name_ru = db[sku]['new_name_ru']
        new_desc_ru = db[sku]['new_desc_ru']
    else:
        print(f"Генерируем текст Gemini (UA + RU) для: {sku}")
        prompt = f"""
Ты опытный маркетолог и SEO-специалист для маркетплейсов.
Твоя задача — сделать рерайт названия и описания товара, чтобы они были уникальными, продающими и привлекали покупателей.
Оригинальное название: {orig_name}
Оригинальное описание: {orig_desc}

Сгенерируй ответ в формате JSON. Обязательно предоставь вариант на украинском языке (ua) и на русском языке (ru). Описание должно быть в формате HTML (используй теги <p>, <ul>, <li>, <strong>).
"""
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=types.Schema(
                        type="OBJECT",
                        properties={
                            "new_title_ua": types.Schema(type="STRING"),
                            "new_description_ua": types.Schema(type="STRING"),
                            "new_title_ru": types.Schema(type="STRING"),
                            "new_description_ru": types.Schema(type="STRING"),
                        }
                    )
                )
            )
            data = json.loads(response.text)
            new_name_ua = data.get('new_title_ua', orig_name)
            new_desc_ua = data.get('new_description_ua', orig_desc)
            new_name_ru = data.get('new_title_ru', orig_name)
            new_desc_ru = data.get('new_description_ru', orig_desc)
            
            db[sku] = {
                'new_name_ua': new_name_ua,
                'new_desc_ua': new_desc_ua,
                'new_name_ru': new_name_ru,
                'new_desc_ru': new_desc_ru
            }
            time.sleep(4.5)
        except Exception as e:
            print(f"Ошибка Gemini: {e}")
            new_name_ua = orig_name
            new_desc_ua = orig_desc
            new_name_ru = orig_name
            new_desc_ru = orig_desc

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
    if vendor_el is not None:
        ET.SubElement(out_offer, "vendor").text = vendor_el.text
    
    for pic in offer.findall('picture'):
        ET.SubElement(out_offer, "picture").text = pic.text
        
    cdata_desc_ru = f"<![CDATA[{new_desc_ru}]]>".replace("<", "___LT___").replace(">", "___GT___")
    cdata_desc_ua = f"<![CDATA[{new_desc_ua}]]>".replace("<", "___LT___").replace(">", "___GT___")
    
    ET.SubElement(out_offer, "description").text = cdata_desc_ru
    ET.SubElement(out_offer, "description_ua").text = cdata_desc_ua
    
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
