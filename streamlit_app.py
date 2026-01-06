import sqlite3
from datetime import date, datetime
import calendar
import streamlit as st
from streamlit_calendar import calendar as st_calendar

DB_PATH = "app.db"


# ---------- DB ----------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ev_date TEXT NOT NULL,          -- YYYY-MM-DD
            start_time TEXT,                -- HH:MM (nullable, 終日はNULLでもOK)
            end_time TEXT,                  -- HH:MM
            category TEXT NOT NULL,          -- class / job / private / work / proposal
            title TEXT NOT NULL,
            place TEXT                       -- store名など（任意）
        );
        """
    )
    conn.commit()
    conn.close()


def add_event(ev_date: str, start_time: str | None, end_time: str | None,
              category: str, title: str, place: str | None = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO events (ev_date, start_time, end_time, category, title, place)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ev_date, start_time, end_time, category, title, place),
    )
    conn.commit()
    conn.close()


def delete_event(event_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()


def fetch_events_in_month(year: int, month: int):
    start = f"{year}-{month:02d}-01"
    # 月末日
    last_day = calendar.monthrange(year, month)[1]
    end = f"{year}-{month:02d}-{last_day:02d}"

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, ev_date, start_time, end_time, category, title, place
        FROM events
        WHERE ev_date BETWEEN ? AND ?
        ORDER BY ev_date ASC, start_time ASC
        """,
        (start, end),
    )
    rows = cur.fetchall()
    conn.close()

    # 日付ごとにまとめる
    by_date = {}
    for r in rows:
        ev = {
            "id": r[0],
            "date": r[1],
            "start": r[2],
            "end": r[3],
            "category": r[4],
            "title": r[5],
            "place": r[6],
        }
        by_date.setdefault(ev["date"], []).append(ev)
    return by_date


# ---------- UI helpers ----------
def badge_html(text: str, kind: str):
    # kind: class/job/private/work/proposal
    styles = {
        "class": "background:#E8F5E9;color:#1B5E20;",
        "job": "background:#E3F2FD;color:#0D47A1;",
        "private": "background:#FCE4EC;color:#880E4F;",
        "work": "background:#E0F7FA;color:#006064;",
        "proposal": "background:#FFF3E0;color:#E65100;",
    }
    style = styles.get(kind, "background:#EEEEEE;color:#212121;")
    return f"""
    <div style="{style} padding:2px 6px; border-radius:10px; font-size:12px; display:inline-block; margin:2px 0;">
      {text}
    </div>
    """


def format_event_label(ev):
    # 時間がある場合はつける
    if ev["start"] and ev["end"]:
        t = f'{ev["start"]}-{ev["end"]} '
    else:
        t = ""
    # place（店名など）があれば先頭に
    p = f'{ev["place"]} ' if ev["place"] else ""
    return f"{p}{t}{ev['title']}"

@st.dialog("予定を追加")
def show_add_event_dialog(selected_date):
    st.write(f"📅 **{selected_date}** の予定を入力してください")

    all_day = st.checkbox("終日（時間なし）", value=True, key="dialog_all_day")

    with st.form("dialog_add"):
        category_ui = st.selectbox(
            "種別",
            ["class（授業）", "job（就活）", "private（遊び）", "work（確定バイト）", "proposal（提案シフト）"],
            key="dialog_cat"
        )
        cat_map = {
            "class（授業）": "class",
            "job（就活）": "job",
            "private（遊び）": "private",
            "work（確定バイト）": "work",
            "proposal（提案シフト）": "proposal"
        }

        
        start_time = end_time = None
        if not all_day:
            col1, col2 = st.columns(2)
            start_time = col1.time_input("開始", value=datetime.strptime("10:00", "%H:%M").time(), key="dialog_st").strftime("%H:%M")
            end_time = col2.time_input("終了", value=datetime.strptime("12:00", "%H:%M").time(), key="dialog_et").strftime("%H:%M")

        title = st.text_input("タイトル", placeholder="例：サンマルク", key="dialog_title")
        place = st.text_input("場所・店名（任意）", key="dialog_place")

        submitted = st.form_submit_button("保存する", use_container_width=True)

    if submitted:
        if not title.strip():
            st.error("タイトルを入力してください")
        else:
            add_event(selected_date, start_time, end_time, cat_map[category_ui], title.strip(), place.strip() or None)
            st.success("保存しました ✅")
            st.rerun()


# ---------- main ----------
st.set_page_config(page_title="バイトシフト作成", layout="wide")
init_db()

st.title("📅 バイトシフト作成アプリ")

# 年月選択
today = date.today()
c1, c2 = st.columns(2)
year = c1.number_input("年", 2020, 2035, today.year, 1)
month = c2.selectbox("月", list(range(1, 13)), index=today.month - 1)


# サイドバー：予定追加
st.sidebar.header("➕ 予定を追加")
category = st.sidebar.selectbox(
    "種別",
    ["class（授業）", "job（就活）", "private（遊び）", "work（確定バイト）", "proposal（提案シフト）"],
)
cat_map = {
    "class（授業）": "class",
    "job（就活）": "job",
    "private（遊び）": "private",
    "work（確定バイト）": "work",
    "proposal（提案シフト）": "proposal",
}
cat = cat_map[category]

ev_date = st.sidebar.date_input("日付", value=today)
all_day = st.sidebar.checkbox("終日（時間なし）", value=True)

start_time = None
end_time = None
if not all_day:
    start_time = st.sidebar.time_input("開始", value=datetime.strptime("10:00", "%H:%M").time()).strftime("%H:%M")
    end_time = st.sidebar.time_input("終了", value=datetime.strptime("12:00", "%H:%M").time()).strftime("%H:%M")

title = st.sidebar.text_input("タイトル", value="例：研究演習 / 面接 / サンマルク")
place = st.sidebar.text_input("場所・店名（任意）", value="")

if st.sidebar.button("追加"):
    if title.strip() == "":
        st.sidebar.error("タイトルを入力してね")
    else:
        add_event(
            ev_date.strftime("%Y-%m-%d"),
            start_time,
            end_time,
            cat,
            title.strip(),
            place.strip() if place.strip() else None,
        )
        st.sidebar.success("追加しました ✅")
        st.rerun()

# DBから月内イベント取得
events_by_date = fetch_events_in_month(year, month)


# DB → FullCalendar events へ変換
fc_events = []
for day_key, evs in events_by_date.items():
    for ev in evs:
        if ev["start"] and ev["end"]:
            start = f"{day_key}T{ev['start']}:00"
            end = f"{day_key}T{ev['end']}:00"
            all_day_flag = False
        else:
            start = day_key
            end = day_key
            all_day_flag = True

        fc_events.append({
            "title": format_event_label(ev),
            "start": start,
            "end": end,
            "allDay": all_day_flag,
        })

calendar_options = {
    "initialView": "dayGridMonth",
    "locale": "ja",
    "height": 650, 
    "initialDate": f"{year}-{month:02d}-01", # 年月選択に追従  # ← マスクリック
    "timeZone": "Asia/Tokyo", 
}


state = st_calendar(
    events=fc_events,
    options=calendar_options,
    callbacks=["dateClick", "eventClick"],    # クリックを拾う
    key=f"calendar_{year}_{month}",           # key重複回避
)

if state and state.get("callback") == "dateClick":
    clicked_date = state["dateClick"].get("dateStr")  # 例: "2026-01-13"
    if clicked_date:
        clicked_date = clicked_date[:10]
    else:
        clicked_date = state["dateClick"]["date"].split("T")[0]  # 保険
    show_add_event_dialog(clicked_date)


# 下：一覧＆削除（デバッグ・操作用）
st.divider()
st.subheader("🗂 この月の予定一覧（削除）")

flat = []
for d, evs in events_by_date.items():
    for ev in evs:
        flat.append(ev)

if not flat:
    st.info("この月の予定はまだありません。左のサイドバーから追加してね。")
else:
    for ev in flat:
        cols = st.columns([5, 1])
        cols[0].write(f"{ev['date']} | {format_event_label(ev)} | [{ev['category']}]")
        if cols[1].button("削除", key=f"del_{ev['id']}"):
            delete_event(ev["id"])
            st.rerun()
st.sidebar.divider()
st.sidebar.header("🧠 シフト提案（テスト）")

if st.sidebar.button("今週のシフトを1件提案"):
    today = date.today().strftime("%Y-%m-%d")
    add_event(
        today,
        "18:00",
        "22:00",
        "proposal",
        "提案シフト",
        "サンマルク",
    )
    st.sidebar.success("提案を追加しました")
    st.rerun()
