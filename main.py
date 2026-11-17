import os, re, math, urllib.parse, requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, FollowEvent, TextMessage, LocationMessage, 
    TextSendMessage, FlexSendMessage, BubbleContainer, 
    BoxComponent, TextComponent, ButtonComponent, URIAction, MessageAction
)

app = FastAPI()
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")

# ⚠️ 1. 請填入「汪喵寵物照護資料庫」的 Google Apps Script /exec 網址
GOOGLE_SHEET_API = "https://script.google.com/macros/s/AKfycbyXqSsQ5exQq4T-i4t4DzCwMIX15fo_NB3J66Ixodax5ktO0WT7MobhRDKoOwLJN4j8ZQ/exec"
# ⚠️ 2. 請填入寵物機器人的 LINE 官方帳號 ID（包含 @ 符號，例如 @123abcde）
LINE_BOT_BASIC_ID = "@650tsvlz"
# ⚠️ 3. 請確認這個寵物機器人的 Render 公開網址（結尾不要加斜線）
RENDER_BASE_URL = "https://onrender.com"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

PET_MAP_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="referrer" content="no-referrer">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no"/>
<title>汪喵居家守護與周邊急診獸醫院地圖</title>
<style>
  body { margin: 0; padding: 0; font-family: -apple-system, sans-serif; background: #f2f4f8; }
  .header { background: #FF9500; color: #fff; padding: 12px 16px; font-weight: bold; font-size: 15px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; }
  .map-viewport { width: 100%; height: 300px; overflow: hidden; position: relative; background: #e2e8f0; border-bottom: 2px solid #cbd5e1; }
  .map-canvas { width: 768px; height: 768px; position: absolute; left: 50%; top: 50%; transform: translate(__OFFSET_X__px, __OFFSET_Y__px); }
  .tile-grid { display: grid; grid-template-columns: repeat(3, 256px); grid-template-rows: repeat(3, 256px); width: 768px; height: 768px; }
  .tile-grid img { width: 256px; height: 256px; display: block; }
  .overlay-svg { position: absolute; top: 0; left: 0; width: 768px; height: 768px; pointer-events: none; }
  .box { padding: 14px; max-width: 600px; margin: 0 auto; }
  .card { background: #fff; border-radius: 12px; padding: 16px; margin-bottom: 12px; box-shadow: 0 2px 6px rgba(0,0,0,0.06); }
  .title { font-weight: bold; font-size: 16px; color: #111; margin-bottom: 6px; }
  .meta { font-size: 13px; color: #555; line-height: 1.5; margin-bottom: 12px; }
  .btn { display: block; width: 100%; box-sizing: border-box; text-align: center; text-decoration: none; padding: 13px; border-radius: 10px; font-size: 15px; font-weight: bold; color: #fff; margin-bottom: 10px; }
  .btn-red { background: #FF3B30; }
  .btn-green { background: #1DB446; }
  .btn-blue { background: #007AFF; }
</style>
</head><body>
<div class="header"><span>🐾 汪喵居家與急診獸醫院地圖</span><span style="font-size:12px;">方圓 1km 守護圈</span></div>
<div class="map-viewport"><div class="map-canvas"><div class="tile-grid">__TILES__</div><svg class="overlay-svg" viewBox="0 0 768 768">__SVG_MARKS__</svg></div></div>
<div class="box">
  <div class="card">
    <div class="title">📍 毛孩住家／寄宿位置</div>
    <div class="meta">__ADDR__<br>座標：__LAT__, __LON__</div>
    <a class="btn btn-blue" href="__NAV_URL__">🧭 導航前往此位置</a>
  </div>
  <div class="card">
    <div class="title">🏥 周邊 24H 急診獸醫院、寵物旅館與用品店</div>
    <a class="btn btn-red" href="__VET_URL__">🚨 搜尋附近 24小時急診獸醫院</a>
    <a class="btn btn-green" href="__HOTEL_URL__">🏨 搜尋附近寵物旅館／美容</a>
    <a class="btn btn-blue" href="__SHOP_URL__">🦴 搜尋附近寵物用品／飼料店</a>
  </div>
</div>
</body></html>"""
def latlon_to_pixel(lat, lon, z=16):
    n = 2.0 ** z
    x = (float(lon) + 180.0) / 360.0 * n * 256.0
    lat_rad = math.radians(float(lat))
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n * 256.0
    return x, y

def parse_latlon(loc_str: str):
    try:
        if "(" in loc_str and ")" in loc_str:
            part = next(iter(loc_str.split("(")[-1].split(")")))
            lat_s, lon_s = part.split(",")
            return float(lat_s.strip()), float(lon_s.strip())
    except Exception:
        pass
    return None, None

def call_sheet(payload: dict):
    try:
        r = requests.post(GOOGLE_SHEET_API, json=payload, timeout=12)
        return r.json()
    except Exception:
        return {}

def get_user_name(uid: str):
    try:
        profile = line_bot_api.get_profile(uid)
        return profile.display_name
    except Exception:
        return "照護者"

@app.get("/")
def root():
    return {"status": "Online", "service": "Pet Care Handoff Bot"}

@app.get("/call", response_class=HTMLResponse)
def direct_call_page(num: str, name: str = "飼主緊急電話"):
    clean_num = re.sub(r"[^0-9+]", "", num)
    safe_name = name.replace("<", "").replace(">", "")
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>正在撥打給 {safe_name}</title>
    <style>
      body {{ font-family: -apple-system, sans-serif; text-align: center; padding: 40px 20px; background: #f2f4f8; }}
      .card {{ background: #fff; border-radius: 16px; padding: 30px 20px; max-width: 400px; margin: 0 auto; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
      .btn {{ display: block; background: #1DB446; color: #fff; text-decoration: none; font-size: 22px; font-weight: bold; padding: 18px; border-radius: 12px; margin-top: 24px; }}
    </style></head><body>
    <div class="card">
      <div style="font-size:18px;color:#555;">準備撥打飼主緊急聯絡電話</div>
      <div style="font-size:28px;font-weight:bold;color:#111;margin:10px 0;">{safe_name}</div>
      <div style="font-size:24px;color:#FF3B30;font-weight:bold;">{clean_num}</div>
      <a class="btn" href="tel:{clean_num}">📞 立即撥出電話</a>
    </div>
    <script>window.onload = function() {{ window.location.href = "tel:{clean_num}"; }};</script>
    </body></html>"""
    return HTMLResponse(content=html)

@app.get("/video", response_class=HTMLResponse)
def video_call_page(room: str, pet: str = "毛孩寶貝"):
    S = chr(47)
    safe_room = re.sub(r"[^a-zA-Z0-9_-]", "", room) or "PetRoomDefault"
    safe_pet = pet.replace("<", "").replace(">", "")
    jitsi_url = f"https:{S}{S}meet.jit.si{S}TaiwanPet_{safe_room}#config.prejoinPageEnabled=false"
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>{safe_pet} · 專屬視訊看毛孩室</title>
    <style>
      body {{ font-family: -apple-system, sans-serif; text-align: center; padding: 36px 20px; background: #f2f4f8; }}
      .card {{ background: #fff; border-radius: 16px; padding: 28px 20px; max-width: 420px; margin: 0 auto; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
      .btn {{ display: block; background: #5856D6; color: #fff; text-decoration: none; font-size: 20px; font-weight: bold; padding: 18px; border-radius: 12px; margin-top: 22px; }}
    </style></head><body>
    <div class="card">
      <div style="font-size:16px;color:#555;">📹 汪喵遠端視訊看毛孩（免下載 App）</div>
      <div style="font-size:26px;font-weight:bold;color:#111;margin:12px 0;">{safe_pet} 的專屬視訊室</div>
      <div style="font-size:13px;color:#666;line-height:1.5;">正在為您開啟高清視訊通話，請允許瀏覽器使用「麥克風與相機」權限：</div>
      <a class="btn" href="{jitsi_url}">📹 立即進入視訊通話</a>
    </div>
    <script>setTimeout(function() {{ window.location.href = "{jitsi_url}"; }}, 600);</script>
    </body></html>"""
    return HTMLResponse(content=html)

@app.get("/pet_map", response_class=HTMLResponse)
def pet_map_view(lat: float, lon: float, addr: str = "毛孩住家"):
    S = chr(47)
    z = 16
    ux, uy = latlon_to_pixel(lat, lon, z)
    cx_tile, cy_tile = int(ux // 256), int(uy // 256)
    origin_x, origin_y = (cx_tile - 1) * 256, (cy_tile - 1) * 256

    tiles_html = []
    for dy in [-1, 0, 1]:
        for dx in [-1, 0, 1]:
            tx, ty = cx_tile + dx, cy_tile + dy
            nlsc_url = f"https:{S}{S}wmts.nlsc.gov.tw{S}wmts{S}EMAP{S}default{S}GoogleMapsCompatible{S}{z}{S}{ty}{S}{tx}"
            osm_url = f"https:{S}{S}tile.openstreetmap.org{S}{z}{S}{tx}{S}{ty}.png"
            tiles_html.append(f'<img src="{nlsc_url}" onerror="this.onerror=null;this.src=\'{osm_url}\';"/>')

    user_px, user_py = ux - origin_x, uy - origin_y
    offset_x, offset_y = round(-user_px, 1), round(-user_py, 1)
    meters_per_px = 156543.03392 * math.cos(math.radians(float(lat))) / (2 ** z)
    radius_px = round(1000.0 / meters_per_px, 1)

    svg_marks = [
        f'<circle cx="{user_px}" cy="{user_py}" r="{radius_px}" fill="#FF9500" fill-opacity="0.14" stroke="#FF9500" stroke-width="2" stroke-dasharray="6,4"/>',
        f'<circle cx="{user_px}" cy="{user_py}" r="10" fill="#FF9500" stroke="#fff" stroke-width="3"/>'
    ]
    safe_addr = addr.replace("<", "").replace(">", "")
    host = "maps." + "google.com"
    base = f"https:{S}{S}{host}{S}"
    nav_url = f"{base}?daddr={lat},{lon}&dirflg=w"
    vet_url = f"{base}?q={urllib.parse.quote('24小時急診獸醫院')}&ll={lat},{lon}&z=15"
    hotel_url = f"{base}?q={urllib.parse.quote('寵物旅館 寵物美容')}&ll={lat},{lon}&z=15"
    shop_url = f"{base}?q={urllib.parse.quote('寵物用品店')}&ll={lat},{lon}&z=15"

    html = (PET_MAP_HTML
            .replace("__OFFSET_X__", str(offset_x))
            .replace("__OFFSET_Y__", str(offset_y))
            .replace("__TILES__", "".join(tiles_html))
            .replace("__SVG_MARKS__", "".join(svg_marks))
            .replace("__ADDR__", safe_addr)
            .replace("__LAT__", str(lat))
            .replace("__LON__", str(lon))
            .replace("__NAV_URL__", nav_url)
            .replace("__VET_URL__", vet_url)
            .replace("__HOTEL_URL__", hotel_url)
            .replace("__SHOP_URL__", shop_url))
    return HTMLResponse(content=html)
def make_pet_card(title: str, subtitle: str, status_text: str, uid: str, lat=None, lon=None, addr="尚未設定", owner_phone: str = "尚未設定"):
    S = chr(47)
    bind_cmd = urllib.parse.quote(f"綁定人員:{uid}")
    share_text = urllib.parse.quote(f"邀請您加入「汪喵平安守護 ＆ 寵物照護日記」守護群（不限人數）！點擊下方連結加入後，每次餵食、鏟屎、散步或異常狀況，您都會即時收到通知：\nhttps:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{bind_cmd}")
    share_uri = f"https:{S}{S}line.me{S}R{S}share?text={share_text}"
    note_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('狀況:')}"
    phone_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('飼主電話:')}"

    clean_phone = re.sub(r"[^0-9]", "", str(owner_phone or ""))
    footer_btns = [
        # 1. 飲食與飲水紀錄
        ButtonComponent(style="primary", color="#1DB446", height="sm", action=MessageAction(label="🥣 放飯正常 / 食慾很好", text="紀錄:餵食:乾乾／罐罐已吃完，飲水正常")),
        ButtonComponent(style="secondary", height="sm", action=MessageAction(label="😿 食慾較差 / 吃得很少", text="異常:餵食:今天食慾較差吃得很少，請留意")),
        # 2. 鏟屎與排泄紀錄
        ButtonComponent(style="primary", color="#007AFF", height="sm", action=MessageAction(label="💩 鏟屎正常 / 便便成形", text="紀錄:排泄:已清理貓砂／撿便，大小便正常")),
        ButtonComponent(style="secondary", height="sm", action=MessageAction(label="🚨 軟便／嘔吐（異常通知）", text="異常:健康:發現軟便或嘔吐狀況，已通知全家")),
        # 3. 散步、驅蟲餵藥與一鍵視訊
        ButtonComponent(style="secondary", height="sm", action=MessageAction(label="🐕 外出散步 / 陪玩放電", text="紀錄:活動:已完成外出散步與陪玩運動")),
        ButtonComponent(style="secondary", height="sm", action=MessageAction(label="💊 已餵驅蟲／保健品", text="紀錄:保健:已按時餵食驅蟲藥／保健品")),
        ButtonComponent(style="secondary", height="sm", action=URIAction(label="✍️ 新增其他特別狀況", uri=note_uri)),
        ButtonComponent(style="secondary", height="sm", action=MessageAction(label="⏰ 設定放飯／驅蟲鬧鐘", text="餵食時間")),
        ButtonComponent(style="primary", color="#5856D6", height="sm", action=MessageAction(label="📹 一鍵視訊看毛孩（免下載）", text="開啟視訊")),
        # 4. 一鍵直撥飼主緊急電話（已設定時同時提供修改／刪除入口）
        *(
            [
                ButtonComponent(
                    style="primary", color="#FF9500", height="sm",
                    action=URIAction(label=f"📞 撥打飼主 ({clean_phone})", uri=f"{RENDER_BASE_URL}/call?num={clean_phone}&name={urllib.parse.quote('毛孩飼主緊急聯絡人')}&openExternalBrowser=1")
                ),
                ButtonComponent(
                    style="secondary", height="sm",
                    action=MessageAction(label="✏️ 修改／刪除飼主電話", text="管理飼主電話")
                )
            ]
            if len(clean_phone) >= 8 else
            [
                ButtonComponent(
                    style="secondary", height="sm",
                    action=URIAction(label="📞 設定飼主緊急聯絡電話", uri=phone_uri)
                )
            ]
        ),
        # 5. 新增／修改／刪除人員、今日日報與修改／刪除狀況
        ButtonComponent(style="secondary", height="sm", action=URIAction(label="👨‍👩‍👧 新增家人／保母 (不限人數)", uri=share_uri)),
        ButtonComponent(style="secondary", height="sm", action=MessageAction(label="👥 修改／刪除已綁定人員名單", text="管理人員")),
        ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 查看今日寵物照護日報", text="今日日報")),
        ButtonComponent(style="secondary", height="sm", action=MessageAction(label="✏️ 修改／刪除今日狀況紀錄", text="修改狀況"))
    ]

    # 6. 24H 急診獸醫院地圖與地址管理
    clean_addr_only = next(iter(str(addr).split("("))).strip() if "(" in str(addr) else str(addr).strip()
    if lat is not None and lon is not None:
        enc_addr = urllib.parse.quote(clean_addr_only or "毛孩住家")
        map_uri = f"{RENDER_BASE_URL}/pet_map?lat={lat}&lon={lon}&addr={enc_addr}&openExternalBrowser=1"
        footer_btns.append(ButtonComponent(style="primary", color="#FF3B30", height="sm", action=URIAction(label="🏥 附近 24H 急診獸醫院地圖", uri=map_uri)))
    elif clean_addr_only and clean_addr_only != "尚未設定":
        host = "maps." + "google.com"
        q_uri = f"https:{S}{S}{host}{S}?q={urllib.parse.quote(clean_addr_only + ' 附近24小時急診獸醫院')}"
        footer_btns.append(ButtonComponent(style="primary", color="#FF3B30", height="sm", action=URIAction(label="🏥 附近 24H 急診獸醫院地圖", uri=q_uri)))

    footer_btns.append(ButtonComponent(style="secondary", height="sm", action=MessageAction(label="🏠 住家／寄宿地址設定修改刪除", text="管理地址")))

    return BubbleContainer(
        size="mega",
        header=BoxComponent(layout="vertical", background_color="#FF9500", padding_all="14px", contents=[
            TextComponent(text=title, weight="bold", size="md", color="#FFFFFF", wrap=True)
        ]),
        body=BoxComponent(layout="vertical", spacing="md", contents=[
            TextComponent(text=subtitle, size="sm", weight="bold", color="#111111", wrap=True),
            BoxComponent(layout="vertical", background_color="#FFF9EB", corner_radius="8px", padding_all="12px", contents=[
                TextComponent(text=status_text, size="xs", color="#333333", wrap=True)
            ]),
            TextComponent(text="🐾 點擊下方按鈕一秒打卡，家人／飼主手機會立刻收到照護交班通知！", size="xxs", color="#666666", wrap=True)
        ]),
        footer=BoxComponent(layout="vertical", spacing="sm", contents=footer_btns)
    )
@app.post("/callback")
async def callback(request: Request):
    sig = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), sig)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"

@handler.add(FollowEvent)
def on_follow(event):
    uid = event.source.user_id
    uname = get_user_name(uid)
    st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
    o_phone = st.get("owner_phone", "尚未設定")
    loc_str = st.get("last_location", "尚未設定")
    lat, lon = parse_latlon(loc_str)
    card = make_pet_card(
        "🐾 汪喵平安守護 ＆ 照護日記 · 已啟動",
        f"嗨 {uname}！歡迎使用毛孩交班守護系統：",
        "點擊下方任何一顆按鈕（放飯、鏟屎、散步、視訊或新增特別狀況），已綁定的家人與飼主都會即時收到通知！",
        uid, lat=lat, lon=lon, addr=loc_str, owner_phone=o_phone
    )
    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="汪喵平安守護已啟動", contents=card))

@handler.add(MessageEvent, message=LocationMessage)
def on_location(event):
    uid = event.source.user_id
    uname = get_user_name(uid)
    addr = event.message.address or "已定位座標"
    lat, lon = event.message.latitude, event.message.longitude
    call_sheet({"action": "location", "user_id": uid, "user_name": uname, "address": addr, "lat": lat, "lon": lon})
    st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
    o_phone = st.get("owner_phone", "尚未設定")
    card = make_pet_card(
        "📍 毛孩住家／寄宿定位與獸醫院地圖已開通",
        "已將此位置設為毛孩的照護座標：",
        f"🏠 登記位置：{addr}\n🏥 點擊下方紅色按鈕，可立即搜尋最近的 24小時急診獸醫院、寵物旅館與用品店！",
        uid, lat=lat, lon=lon, addr=addr, owner_phone=o_phone
    )
    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="毛孩定位更新成功", contents=card))

@handler.add(MessageEvent, message=TextMessage)
def on_text(event):
    uid = event.source.user_id
    uname = get_user_name(uid)
    txt = event.message.text.strip()

    # 0. 一鍵開啟專屬視訊看毛孩並同步通知所有人員
    if txt in ["開啟視訊", "視訊", "視訊看毛孩", "打視訊"]:
        st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
        p_name = st.get("pet_name", "毛孩寶貝")
        f_ids = st.get("family_ids", [])
        room_code = uid[-12:] if len(uid) >= 12 else uid
        video_uri = f"{RENDER_BASE_URL}/video?room={room_code}&pet={urllib.parse.quote(p_name)}&openExternalBrowser=1"

        if len(f_ids) > 0:
            invite_bubble = BubbleContainer(
                size="mega",
                header=BoxComponent(layout="vertical", background_color="#5856D6", padding_all="14px", contents=[
                    TextComponent(text=f"📹 {p_name} · 遠端視訊看毛孩邀請", weight="bold", size="md", color="#FFFFFF", wrap=True)
                ]),
                body=BoxComponent(layout="vertical", spacing="sm", contents=[
                    TextComponent(text=f"照護者「{uname}」已開啟專屬視訊室，快進來看看「{p_name}」現在可愛的模樣吧！", size="sm", weight="bold", color="#111111", wrap=True),
                    TextComponent(text="點擊下方紫色按鈕即可透過瀏覽器直接加入視訊（免下載任何 App）：", size="xs", color="#555555", wrap=True)
                ]),
                footer=BoxComponent(layout="vertical", contents=[
                    ButtonComponent(style="primary", color="#5856D6", height="sm", action=URIAction(label="📹 立即加入視訊看毛孩", uri=video_uri))
                ])
            )
            for fid in f_ids:
                try:
                    line_bot_api.push_message(fid, FlexSendMessage(alt_text=f"📹 {p_name} 視訊看毛孩邀請", contents=invite_bubble))
                except Exception:
                    pass

        self_card = BubbleContainer(
            size="mega",
            header=BoxComponent(layout="vertical", background_color="#5856D6", padding_all="14px", contents=[
                TextComponent(text="📹 專屬視訊看毛孩室已建立", weight="bold", size="md", color="#FFFFFF", wrap=True)
            ]),
            body=BoxComponent(layout="vertical", spacing="sm", contents=[
                TextComponent(text=f"已同步發送視訊邀請給 {len(f_ids)} 位家人／飼主！" if len(f_ids) > 0 else "視訊室已準備就緒（尚未綁定家人時也可直接開啟）！", size="sm", weight="bold", color="#111111", wrap=True),
                TextComponent(text="點擊下方紫色按鈕即可開啟手機鏡頭，與家人一起看看毛孩狀況：", size="xs", color="#555555", wrap=True)
            ]),
            footer=BoxComponent(layout="vertical", spacing="sm", contents=[
                ButtonComponent(style="primary", color="#5856D6", height="sm", action=URIAction(label="📹 立即開啟視訊鏡頭", uri=video_uri)),
                ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 返回今日寵物照護日報", text="今日日報"))
            ])
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="專屬視訊室已建立", contents=self_card))
        return
    # 1. 處理日常一鍵照護打卡（格式：紀錄:類別:詳細內容）
    if txt.startswith("紀錄:"):
        parts = txt.split(":", 2)
        cat = parts if len(parts) > 1 else "照護紀錄"
        detail = parts if len(parts) > 2 else txt
        res = call_sheet({"action": "log_care", "user_id": uid, "user_name": uname, "category": cat, "detail": detail, "is_abnormal": False})
        t_str = res.get("time", "剛剛")
        f_cnt = res.get("family_count", 0)
        pet_n = res.get("pet_name", "毛孩寶貝")
        st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
        o_phone = st.get("owner_phone", "尚未設定")
        loc_str = st.get("last_location", "尚未設定")
        lat, lon = parse_latlon(loc_str)

        notify_note = f"✅ 已同步通知 {f_cnt} 位家人／飼主！" if f_cnt > 0 else "💡 尚未綁定家人／保母（點下方按鈕可邀請加入）"
        card = make_pet_card(
            f"✅ {cat}已紀錄完成",
            f"毛孩：{pet_n}　｜　時間：{t_str}",
            f"📋 狀況內容：{detail}\n🔔 通知狀態：{notify_note}",
            uid, lat=lat, lon=lon, addr=loc_str, owner_phone=o_phone
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text=f"{cat}紀錄完成", contents=card))
        return

    # 1-1. 處理異常健康狀況預警（格式：異常:類別:詳細內容）
    if txt.startswith("異常:"):
        parts = txt.split(":", 2)
        cat = parts if len(parts) > 1 else "健康異常"
        detail = parts if len(parts) > 2 else txt
        res = call_sheet({"action": "log_care", "user_id": uid, "user_name": uname, "category": cat, "detail": detail, "is_abnormal": True})
        t_str = res.get("time", "剛剛")
        f_cnt = res.get("family_count", 0)
        pet_n = res.get("pet_name", "毛孩寶貝")
        st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
        o_phone = st.get("owner_phone", "尚未設定")
        loc_str = st.get("last_location", "尚未設定")
        lat, lon = parse_latlon(loc_str)

        card = make_pet_card(
            "🚨 毛孩異常狀況已記錄並通報！",
            f"毛孩：{pet_n}　｜　時間：{t_str}",
            f"⚠️ 異常內容：{detail}\n🔔 已優先發送警報通知 {f_cnt} 位家人／飼主！如需就醫可點擊下方紅色按鈕搜尋 24H 急診獸醫院。",
            uid, lat=lat, lon=lon, addr=loc_str, owner_phone=o_phone
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="毛孩異常狀況通報", contents=card))
        return

    # 1-2. 新增其他特別狀況（例如：狀況:今天在陽台曬太陽睡著了，精神很好）
    if txt.startswith("狀況:") or txt.startswith("狀況：") or txt.startswith("備忘:") or txt.startswith("備忘："):
        note_content = txt[3:].strip()
        if not note_content:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="✍️ 請在「狀況:」後面直接輸入毛孩的特別狀況喔！\n例如：狀況:今天在陽台曬太陽睡著了，精神很好"))
            return
        res = call_sheet({"action": "log_care", "user_id": uid, "user_name": uname, "category": "特別狀況", "detail": note_content, "is_abnormal": False})
        t_str = res.get("time", "剛剛")
        f_cnt = res.get("family_count", 0)
        pet_n = res.get("pet_name", "毛孩寶貝")
        st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
        o_phone = st.get("owner_phone", "尚未設定")
        loc_str = st.get("last_location", "尚未設定")
        lat, lon = parse_latlon(loc_str)

        notify_note = f"✅ 已同步通知 {f_cnt} 位家人／飼主！" if f_cnt > 0 else "💡 尚未綁定家人／保母（點下方按鈕可邀請加入）"
        card = make_pet_card(
            "✍️ 特別狀況已新增完成",
            f"毛孩：{pet_n}　｜　時間：{t_str}",
            f"📝 狀況內容：{note_content}\n🔔 通知狀態：{notify_note}",
            uid, lat=lat, lon=lon, addr=loc_str, owner_phone=o_phone
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="特別狀況新增完成", contents=card))
        return
    # 2. 修改／刪除今日已記錄的照護狀況（支援文字覆蓋修改與單筆刪除）
    if txt in ["修改狀況", "刪除狀況", "修改紀錄", "編輯狀況"]:
        res = call_sheet({"action": "get_today_items", "user_id": uid})
        items = res.get("items", [])
        body_items = [
            TextComponent(text="如需修改或刪除今日狀況，請點下方對應項目：", size="xs", color="#555555", wrap=True),
            TextComponent(text="• 點「✏️ 改」：可直接輸入新文字覆蓋該筆狀況內容\n• 點「❌ 刪」：立即刪除該筆錯誤紀錄", size="xxs", color="#888888", wrap=True)
        ]
        footer_items = []

        if len(items) == 0:
            body_items.append(TextComponent(text="（今天目前還沒有任何狀況紀錄喔！）", size="xs", color="#888888", margin="md"))
        else:
            S = chr(47)
            for it in items[-5:]:
                r_num = it.get("row_num")
                short_detail = str(it.get("detail", ""))[:10]
                edit_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote(f'改狀況:{r_num}:')}"
                footer_items.append(
                    ButtonComponent(style="secondary", height="sm", action=URIAction(label=f"✏️ 改 [{it.get('time')}] {short_detail}"[:38], uri=edit_uri))
                )
                footer_items.append(
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label=f"❌ 刪 [{it.get('time')}] {short_detail}"[:38], text=f"刪狀況:{r_num}"))
                )

        footer_items.append(
            ButtonComponent(style="primary", color="#FF9500", height="sm", action=MessageAction(label="📊 返回今日寵物照護日報", text="今日日報"))
        )

        edit_card = BubbleContainer(
            size="mega",
            header=BoxComponent(layout="vertical", background_color="#FF9500", padding_all="14px", contents=[
                TextComponent(text="✏️ 修改／刪除今日照護狀況", weight="bold", size="md", color="#FFFFFF", wrap=True)
            ]),
            body=BoxComponent(layout="vertical", spacing="md", contents=body_items),
            footer=BoxComponent(layout="vertical", spacing="sm", contents=footer_items)
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="修改／刪除今日照護狀況", contents=edit_card))
        return

    if txt.startswith("改狀況:"):
        parts = txt.split(":", 2)
        if len(parts) >= 3 and parts[2].strip():
            row_num = parts[1].strip()
            new_text = parts[2].strip()
            call_sheet({"action": "edit_log", "user_id": uid, "row_num": row_num, "detail": new_text})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ 已成功修改該筆狀況為：「{new_text}」！\n輸入「今日日報」可查看最新完整紀錄。"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請在冒號後面輸入修改後的狀況文字喔！"))
        return

    if txt.startswith("刪狀況:"):
        row_num = txt[4:].strip()
        call_sheet({"action": "delete_log", "user_id": uid, "row_num": row_num})
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="✅ 已成功刪除該筆錯誤狀況紀錄！\n請點擊主畫面上的按鈕重新記錄正確狀態。"))
        return

    # 3. 設定每日定時放飯／保健提醒時間（HH:MM）
    if txt in ["餵食時間", "放飯時間", "鬧鐘設定"]:
        S = chr(47)
        custom_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('放飯:')}"
        st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
        cur_t = st.get("care_times", "尚未設定")
        rem_card = BubbleContainer(
            size="mega",
            header=BoxComponent(layout="vertical", background_color="#FF9500", padding_all="14px", contents=[
                TextComponent(text="⏰ 汪喵定時放飯／保健鬧鐘", weight="bold", size="md", color="#FFFFFF", wrap=True)
            ]),
            body=BoxComponent(layout="vertical", spacing="md", contents=[
                TextComponent(text=f"目前設定時段：{cur_t}", size="sm", weight="bold", color="#111111", wrap=True),
                TextComponent(text="時間一到，系統會自動推播提醒卡片，點一下「✅ 已放飯換水」即可順便完成交班！", size="xs", color="#555555", wrap=True),
                BoxComponent(layout="horizontal", spacing="sm", contents=[
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label="早晚8點", text="放飯:08:00, 20:00")),
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label="早中晚三餐", text="放飯:08:00, 13:00, 19:00"))
                ])
            ]),
            footer=BoxComponent(layout="vertical", spacing="sm", contents=[
                ButtonComponent(style="primary", color="#007AFF", height="sm", action=URIAction(label="✏️ 自訂多時段（如 08:30, 21:00）", uri=custom_uri)),
                ButtonComponent(style="secondary", height="sm", action=MessageAction(label="🔕 關閉放飯提醒", text="放飯:關閉"))
            ])
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="汪喵定時放飯鬧鐘", contents=rem_card))
        return

    if txt.startswith("放飯:") or txt.startswith("放飯："):
        t_val = txt[3:].strip().replace("，", ", ").replace("：", ":")
        call_sheet({"action": "set_care_times", "user_id": uid, "user_name": uname, "care_times": t_val})
        msg = "🔕 已關閉每日定時放飯提醒。" if t_val == "關閉" else f"🥣 設定成功！系統將於每天【{t_val}】準時推播放飯換水提醒卡片！"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
        return

    # 4. 新增／修改／刪除飼主緊急電話
    if txt in ["管理飼主電話", "修改飼主電話", "飼主電話"]:
        S = chr(47)
        edit_phone_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('飼主電話:')}"
        st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
        cur_phone = st.get("owner_phone", "尚未設定")

        phone_card = BubbleContainer(
            size="mega",
            header=BoxComponent(layout="vertical", background_color="#FF9500", padding_all="14px", contents=[
                TextComponent(text="📞 飼主緊急電話管理", weight="bold", size="md", color="#FFFFFF", wrap=True)
            ]),
            body=BoxComponent(layout="vertical", spacing="md", contents=[
                TextComponent(text=f"目前登記號碼：{cur_phone}", size="sm", weight="bold", color="#111111", wrap=True),
                TextComponent(text="您可以點擊下方按鈕輸入新號碼覆蓋修改，或直接刪除目前的緊急聯絡電話：", size="xs", color="#555555", wrap=True)
            ]),
            footer=BoxComponent(layout="vertical", spacing="sm", contents=[
                ButtonComponent(style="primary", color="#007AFF", height="sm", action=URIAction(label="✏️ 輸入／修改新號碼", uri=edit_phone_uri)),
                ButtonComponent(style="primary", color="#FF3B30", height="sm", action=MessageAction(label="🗑️ 刪除目前飼主電話", text="刪除飼主電話")),
                ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 返回今日寵物照護日報", text="今日日報"))
            ])
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="飼主緊急電話管理", contents=phone_card))
        return

    if txt in ["刪除飼主電話", "清除飼主電話"]:
        call_sheet({"action": "set_owner_phone", "user_id": uid, "user_name": uname, "phone": "尚未設定"})
        st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
        loc_str = st.get("last_location", "尚未設定")
        lat, lon = parse_latlon(loc_str)
        card = make_pet_card(
            "🗑️ 飼主緊急電話已刪除",
            "已清空原本登記的飼主聯絡號碼",
            "主畫面按鈕已恢復為「📞 設定飼主緊急聯絡電話」，隨時可重新設定新號碼！",
            uid, lat=lat, lon=lon, addr=loc_str, owner_phone="尚未設定"
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="飼主緊急電話已刪除", contents=card))
        return

    if txt.startswith("飼主電話:") or txt.startswith("飼主電話："):
        p_val = txt[5:].strip()
        if not p_val:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請在「飼主電話:」後面輸入手機或市話號碼喔！\n例如：飼主電話:0912345678"))
            return
        call_sheet({"action": "set_owner_phone", "user_id": uid, "user_name": uname, "phone": p_val})
        st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
        loc_str = st.get("last_location", "尚未設定")
        lat, lon = parse_latlon(loc_str)
        card = make_pet_card(
            "📞 飼主緊急直撥電話已設定",
            f"緊急聯絡號碼：{p_val}",
            "現在只要點擊下方橘色按鈕，系統就會透過外部瀏覽器直接喚醒手機撥號盤聯繫飼主！",
            uid, lat=lat, lon=lon, addr=loc_str, owner_phone=p_val
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="飼主緊急直撥電話已設定", contents=card))
        return
    # 5. 住家／寄宿地址設定、修改與刪除
    if txt in ["管理地址", "住家地址", "修改地址", "地址"]:
        S = chr(47)
        edit_addr_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('地址:')}"
        loc_uri = f"https:{S}{S}line.me{S}R{S}nv{S}location{S}"
        st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
        cur_loc = st.get("last_location", "尚未設定")

        addr_card = BubbleContainer(
            size="mega",
            header=BoxComponent(layout="vertical", background_color="#FF9500", padding_all="14px", contents=[
                TextComponent(text="🏠 毛孩住家／寄宿地址管理", weight="bold", size="md", color="#FFFFFF", wrap=True)
            ]),
            body=BoxComponent(layout="vertical", spacing="md", contents=[
                TextComponent(text=f"目前登記位置：{cur_loc}", size="sm", weight="bold", color="#111111", wrap=True),
                TextComponent(text="您可以直接打字輸入門牌地址（例如：地址:新北市五股區成泰路一段100號），或傳送 GPS 定位座標：", size="xs", color="#555555", wrap=True)
            ]),
            footer=BoxComponent(layout="vertical", spacing="sm", contents=[
                ButtonComponent(style="primary", color="#007AFF", height="sm", action=URIAction(label="✏️ 直接輸入／修改文字地址", uri=edit_addr_uri)),
                ButtonComponent(style="secondary", height="sm", action=URIAction(label="📍 傳送 GPS 定位座標", uri=loc_uri)),
                ButtonComponent(style="primary", color="#FF3B30", height="sm", action=MessageAction(label="🗑️ 刪除目前登記地址", text="刪除地址")),
                ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 返回今日寵物照護日報", text="今日日報"))
            ])
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="毛孩住家地址管理", contents=addr_card))
        return

    if txt.startswith("地址:") or txt.startswith("地址："):
        addr_val = txt[3:].strip()
        if not addr_val:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請在「地址:」後面輸入完整住家或寵物旅館地址喔！"))
            return
        res = call_sheet({"action": "set_address", "user_id": uid, "user_name": uname, "address": addr_val})
        st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
        o_phone = st.get("owner_phone", "尚未設定")
        new_loc = res.get("last_location", addr_val)
        lat, lon = parse_latlon(new_loc)
        card = make_pet_card(
            "🏠 毛孩住家／寄宿地址已更新",
            f"登記地址：{new_loc}",
            "現在點擊下方紅色地圖按鈕，即可直接搜尋附近 24小時急診獸醫院與寵物旅館！",
            uid, lat=lat, lon=lon, addr=new_loc, owner_phone=o_phone
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="毛孩住家地址已更新", contents=card))
        return

    if txt in ["刪除地址", "清除地址"]:
        call_sheet({"action": "set_address", "user_id": uid, "user_name": uname, "address": "尚未設定"})
        st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
        o_phone = st.get("owner_phone", "尚未設定")
        card = make_pet_card(
            "🗑️ 毛孩住家地址已刪除",
            "已清空原本登記的地址與定位座標",
            "隨時可點擊下方「🏠 住家／寄宿地址設定修改刪除」重新登記新位置！",
            uid, addr="尚未設定", owner_phone=o_phone
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="毛孩住家地址已刪除", contents=card))
        return

    # 6. 新增／修改／刪除家人與保母人員名單（不限人數上限）
    if txt in ["管理人員", "人員名單", "修改人員", "刪除人員"]:
        S = chr(47)
        bind_cmd = urllib.parse.quote(f"綁定人員:{uid}")
        share_text = urllib.parse.quote(f"邀請您加入「汪喵平安守護 ＆ 寵物照護日記」守護群（不限人數）！點擊下方連結加入後，每次餵食、鏟屎、散步或異常狀況，您都會即時收到通知：\nhttps:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{bind_cmd}")
        share_uri = f"https:{S}{S}line.me{S}R{S}share?text={share_text}"

        st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
        f_ids = st.get("family_ids", [])

        body_contents = [
            TextComponent(text=f"目前已綁定守護人員：{len(f_ids)} 位（不限人數上限）", size="sm", weight="bold", color="#111111"),
            TextComponent(text="照護打卡與視訊邀請會同步發送給以下所有成員。如需移除特定家人／保母，請直接點擊下方移除按鈕：", size="xs", color="#555555", wrap=True)
        ]
        footer_btns = []

        if len(f_ids) == 0:
            body_contents.append(TextComponent(text="（目前尚未綁定任何家人或保母人員）", size="xs", color="#888888", margin="md"))
        else:
            for idx, fid in enumerate(f_ids[-10:], 1):
                f_name = get_user_name(fid)
                disp_f = f_name if f_name != "照護者" else f"人員 #{idx} ({fid[:6]}...)"
                footer_btns.append(
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label=f"❌ 移除：{disp_f}"[:38], text=f"移除人員:{fid}"))
                )
            footer_btns.append(
                ButtonComponent(style="primary", color="#FF3B30", height="sm", action=MessageAction(label="🗑️ 一鍵清空全部人員名單", text="清空人員"))
            )

        footer_btns.append(ButtonComponent(style="primary", color="#007AFF", height="sm", action=URIAction(label="➕ 新增家人／保母（不限人數）", uri=share_uri)))
        footer_btns.append(ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 返回今日寵物照護日報", text="今日日報")))

        fam_card = BubbleContainer(
            size="mega",
            header=BoxComponent(layout="vertical", background_color="#007AFF", padding_all="14px", contents=[
                TextComponent(text="👥 家人／保母人員管理（新增與移除）", weight="bold", size="md", color="#FFFFFF", wrap=True)
            ]),
            body=BoxComponent(layout="vertical", spacing="md", contents=body_contents),
            footer=BoxComponent(layout="vertical", spacing="sm", contents=footer_btns)
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="家人／保母人員管理", contents=fam_card))
        return

    if txt.startswith("移除人員:"):
        target_fid = txt[5:].strip()
        res = call_sheet({"action": "remove_family", "user_id": uid, "family_id": target_fid})
        rem_cnt = res.get("count", 0)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ 已成功移除該位人員！目前剩餘 {rem_cnt} 位毛孩守護成員。"))
        return

    if txt in ["清空人員", "全部移除人員"]:
        call_sheet({"action": "clear_family", "user_id": uid})
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🗑️ 已為您清空所有家人／保母人員名單！隨時可透過邀請連結重新加入。"))
        return

    # 7. 設定毛孩名字與綁定人員
    if txt.startswith("毛孩:") or txt.startswith("毛孩：") or txt.startswith("寵物:") or txt.startswith("寵物："):
        p_val = txt[3:].strip()
        if p_val:
            call_sheet({"action": "set_pet", "user_id": uid, "user_name": uname, "pet_name": p_val})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🐾 已將毛孩名字更新為「{p_val}」！接下來所有照護交班與視訊通知都會顯示這個名字。"))
        return

    if txt.startswith("綁定人員:"):
        caregiver_uid = txt[5:].strip()
        if caregiver_uid == uid:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 不能綁定自己喔！請把邀請卡片轉傳給其他家人或寵物保母點擊。"))
            return
        res = call_sheet({"action": "bind_family", "user_id": caregiver_uid, "family_id": uid})
        p_name = res.get("pet_name", "毛孩寶貝")
        cnt = res.get("count", 1)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🤝 加入成功！您已成為「{p_name}」的第 {cnt} 位守護成員（不限人數上限）。\n只要照護者點擊放飯、鏟屎、散步、特別狀況或開啟視訊，您都會即時收到通知，每天 18:00 也會收到今日寵物照護日報！"))
        return

    # 8. 查看今日寵物照護日報與主操作面板
    st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
    p_name = st.get("pet_name", "毛孩寶貝")
    f_cnt = st.get("family_count", 0)
    o_phone = st.get("owner_phone", "尚未設定")
    c_times = st.get("care_times", "尚未設定")
    loc_str = st.get("last_location", "尚未設定")
    logs = st.get("today_logs", [])
    logs_txt = "\n".join(logs) if len(logs) > 0 else "（今日尚無紀錄，點擊下方按鈕即可開始為毛孩打卡交班）"

    lat, lon = parse_latlon(loc_str)
    card = make_pet_card(
        f"🐾 {p_name} · 今日寵物照護日報",
        f"守護群：{f_cnt} 位（不限上限） ｜ 放飯鬧鐘：{c_times}",
        f"{logs_txt}\n\n🏠 登記位置：{loc_str}\n💡 輸入「毛孩:橘子」可改名字；點「✍️ 新增其他特別狀況」可自由輸入備忘。",
        uid, lat=lat, lon=lon, addr=loc_str, owner_phone=o_phone
    )
    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="今日寵物照護日報", contents=card))

