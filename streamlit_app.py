from __future__ import annotations
import pandas as pd
import sqlite3
import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional
import streamlit as st
from streamlit_calendar import calendar as st_calendar

DB_PATH = "app.db"

SHIFT_TEMPLATES = {
    "成城石井": [("10:00", "14:00"), ("17:00", "22:00"), ("18:00", "22:00")],
    "サンマルク": [
        ("10:00", "16:00"), ("11:00", "17:00"), ("12:00", "18:00"),
        ("13:00", "19:00"), ("14:00", "20:00"), ("16:00", "22:00"),
        ("14:00", "18:00"), ("17:00", "22:00"), ("18:00", "22:00"),
    ],
}
BUFFER_BEFORE_AFTER_MIN = 60
TRAVEL_BETWEEN_WORKPLACES_MIN = 60
WORKDAY_PENALTY = 250


# ---------- DB ----------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ev_date TEXT NOT NULL,          -- YYYY-MM-DD
        start_time TEXT,                -- HH:MM (nullable, 終日はNULLでもOK)
        end_time TEXT,                  -- HH:MM
        category TEXT NOT NULL,          -- class / job / private / work / proposal
        title TEXT NOT NULL,
        place TEXT                       -- store名など（任意）
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS availability (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workplace TEXT NOT NULL,         -- サンマルク / 成城石井
        day_type TEXT NOT NULL,          -- weekday / weekend / dow
        dow INTEGER,                     -- 0=Mon..6=Sun（day_type='dow'の時だけ）
        start_time TEXT NOT NULL,        -- HH:MM
        end_time TEXT NOT NULL           -- HH:MM
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        max_hours_per_day INTEGER,
        max_hours_per_week INTEGER
    );
    """)
    cur.execute("""
    INSERT OR IGNORE INTO settings (id, max_hours_per_day, max_hours_per_week)
    VALUES (1, 6, 20);
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS wages (
        workplace TEXT PRIMARY KEY,
        hourly_wage INTEGER NOT NULL
    );
    """)

    conn.commit()
    conn.close()


def add_event(ev_date: str, start_time: Optional[str], end_time: Optional[str],
             category: str, title: str, place: Optional[str] = None):
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

def update_event(event_id: int, ev_date: str, start_time: Optional[str], end_time: Optional[str],
                 category: str, title: str, place: Optional[str] = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE events
        SET ev_date=?, start_time=?, end_time=?, category=?, title=?, place=?
        WHERE id=?
        """,
        (ev_date, start_time, end_time, category, title, place, event_id),
    )
    conn.commit()
    conn.close()


def fetch_events_in_month(year: int, month: int):
    start = f"{year}-{month:02d}-01"
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


def fetch_events_between(start_date: str, end_date: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, ev_date, start_time, end_time, category, title, place
        FROM events
        WHERE ev_date BETWEEN ? AND ?
        ORDER BY ev_date ASC, start_time ASC
        """,
        (start_date, end_date),
    )
    rows = cur.fetchall()
    conn.close()

    return [
        {
            "id": r[0],
            "date": r[1],
            "start": r[2],
            "end": r[3],
            "category": r[4],
            "title": r[5],
            "place": r[6],
        }
        for r in rows
    ]

def fetch_event_by_id(event_id: int) -> Optional[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, ev_date, start_time, end_time, category, title, place
        FROM events
        WHERE id = ?
        """,
        (event_id,),
    )
    r = cur.fetchone()
    conn.close()
    if not r:
        return None
    return {
        "id": r[0],
        "date": r[1],
        "start": r[2],
        "end": r[3],
        "category": r[4],
        "title": r[5],
        "place": r[6],
    }

# ---------- DB (proposal config) ----------
def upsert_settings(max_day: int, max_week: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE settings SET max_hours_per_day=?, max_hours_per_week=? WHERE id=1",
        (max_day, max_week),
    )
    conn.commit()
    conn.close()


def get_settings() -> tuple[int, int]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT max_hours_per_day, max_hours_per_week FROM settings WHERE id=1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return 6, 20
    return int(row[0] or 6), int(row[1] or 20)


def upsert_wage(workplace: str, hourly_wage: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO wages(workplace, hourly_wage) VALUES(?, ?) "
        "ON CONFLICT(workplace) DO UPDATE SET hourly_wage=excluded.hourly_wage",
        (workplace, hourly_wage),
    )
    conn.commit()
    conn.close()


def get_wages() -> dict[str, int]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT workplace, hourly_wage FROM wages")
    rows = cur.fetchall()
    conn.close()
    return {r[0]: int(r[1]) for r in rows}


def add_availability(workplace: str, day_type: str, dow: Optional[int], start_time: str, end_time: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO availability(workplace, day_type, dow, start_time, end_time)
        VALUES (?, ?, ?, ?, ?)
        """,
        (workplace, day_type, dow, start_time, end_time),
    )
    conn.commit()
    conn.close()


def delete_availability(avail_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM availability WHERE id=?", (avail_id,))
    conn.commit()
    conn.close()


def get_availabilities() -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, workplace, day_type, dow, start_time, end_time
        FROM availability
        ORDER BY workplace, day_type, dow, start_time
        """
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "workplace": r[1],
            "day_type": r[2],
            "dow": r[3],
            "start_time": r[4],
            "end_time": r[5],
        }
        for r in rows
    ]


def delete_proposals_in_range(start_date: str, end_date: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM events
        WHERE category='proposal' AND ev_date BETWEEN ? AND ?
        """,
        (start_date, end_date),
    )
    conn.commit()
    conn.close()


def convert_proposals_to_work(start_date: str, end_date: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE events
        SET category='work'
        WHERE category='proposal' AND ev_date BETWEEN ? AND ?
        """,
        (start_date, end_date),
    )
    conn.commit()
    conn.close()


# ---------- Proposal logic ----------
def _t(s: str) -> time:
    return datetime.strptime(s, "%H:%M").time()

def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())

def month_range(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    last = date(year, month, last_day)
    return first, last

def iter_week_starts_in_month(year: int, month: int) -> list[date]:
    first, last = month_range(year, month)
    start = monday_of(first)
    week_starts = []
    d = start
    while d <= last:
        week_starts.append(d)
        d += timedelta(days=7)
    return week_starts


def propose_week_fixed_slots(
    week_start_date: date,
    max_day: int,
    max_week: int,
    wages: dict[str, int],
    events: list[dict],
    seed: int = 0,
    avail_days: dict[str, list[bool]] | None = None,
):
    import random
    rnd = random.Random(seed)

    busy = [e for e in events if e["category"] in ("class", "job", "private", "work", "proposal")]
    busy_days = {e["date"] for e in busy if e.get("date")}

    def to_dt(d: date, hm: str) -> datetime:
        return datetime.combine(d, _t(hm))

    def overlaps(a_s: datetime, a_e: datetime, b_s: datetime, b_e: datetime) -> bool:
        return (a_s < b_e) and (b_s < a_e)

    def is_busy_with_buffer(d: date, s: str, e: str) -> bool:
        ss = to_dt(d, s) - timedelta(minutes=BUFFER_BEFORE_AFTER_MIN)
        ee = to_dt(d, e) + timedelta(minutes=BUFFER_BEFORE_AFTER_MIN)
        ds = d.strftime("%Y-%m-%d")

        for b in busy:
            if b["date"] != ds:
                continue
            if b["start"] is None or b["end"] is None:
                return True
            bs = to_dt(d, b["start"])
            be = to_dt(d, b["end"])
            if overlaps(ss, ee, bs, be):
                return True
        return False


    def conflicts_with_picked(d: date, s: str, e: str, workplace: str, picked: list[dict]) -> bool:
        ss = to_dt(d, s)
        ee = to_dt(d, e)
        for p in picked:
            if p["date"] != d.strftime("%Y-%m-%d"):
                continue
            ps = to_dt(d, p["start"])
            pe = to_dt(d, p["end"])

            if p["workplace"] == workplace:
                if overlaps(ss, ee, ps, pe):
                    return True
            else:
                gap1 = (ss - pe).total_seconds() / 60  
                gap2 = (ps - ee).total_seconds() / 60  
                if not (gap1 >= TRAVEL_BETWEEN_WORKPLACES_MIN or gap2 >= TRAVEL_BETWEEN_WORKPLACES_MIN):
                    return True
        return False

    # ---- 候補生成（固定枠＋曜日ON/OFF）----
    candidates = []
    for i in range(7):
        d = week_start_date + timedelta(days=i)
        dow = d.weekday()
        ds = d.strftime("%Y-%m-%d")

        for w, shifts in SHIFT_TEMPLATES.items():
            # 曜日ON/OFF
            if avail_days is not None and not avail_days.get(w, [True] * 7)[dow]:
                continue

            wage = wages.get(w, 0)

            for (s, e) in shifts:
                if w == "サンマルク" and dow == 1 and e == "22:00":
                    continue

                if is_busy_with_buffer(d, s, e):
                    continue

                hours = int((to_dt(d, e) - to_dt(d, s)).total_seconds() // 3600)
                candidates.append({
                    "date": ds,
                    "start": s,
                    "end": e,
                    "workplace": w,
                    "hours": hours,
                    "income": hours * wage,
                })

    # ---- 選択（稼ぎ最大＋働く日の増加を少し抑える）----
    picked = []
    day_hours: dict[str, int] = {}
    workdays = set()
    total_hours = 0

    BUSY_DAY_PENALTY = 3000
    BUSY_DAY_PENALTY_STM = 7000  

    def score(c):
        sc = c["income"]

        if c["date"] in busy_days:
            if c["workplace"] == "サンマルク":
                sc -= BUSY_DAY_PENALTY_STM
            else:
                sc -= BUSY_DAY_PENALTY

        if c["date"] not in workdays:
            sc -= WORKDAY_PENALTY

        sc -= day_hours.get(c["date"], 0) * 50
        sc += rnd.randint(0, 30)
        return sc


    while True:
        best = None
        best_sc = -10**18

        for c in candidates:
            if total_hours + c["hours"] > max_week:
                continue
            if day_hours.get(c["date"], 0) + c["hours"] > max_day:
                continue

            d_obj = datetime.strptime(c["date"], "%Y-%m-%d").date()
            if conflicts_with_picked(d_obj, c["start"], c["end"], c["workplace"], picked):
                continue

            sc = score(c)
            if sc > best_sc:
                best_sc = sc
                best = c

        if best is None:
            break

        picked.append(best)
        total_hours += best["hours"]
        day_hours[best["date"]] = day_hours.get(best["date"], 0) + best["hours"]
        workdays.add(best["date"])

        candidates = [x for x in candidates if not (
            x["date"] == best["date"]
            and x["start"] == best["start"]
            and x["end"] == best["end"]
            and x["workplace"] == best["workplace"]
        )]

    picked.sort(key=lambda x: (x["date"], x["start"]))
    return picked



# ---------- UI helpers ----------
def format_event_label(ev):
    prefix = "✅ " if ev["category"] == "work" else ""
    name = ev["place"] or ev["title"]  # 店名優先
    if ev["start"] and ev["end"]:
        return f'{prefix}{ev["start"]}-{ev["end"]} {name}'
    return f'{prefix}{name}'


@st.dialog("予定をまとめて追加（単日 / 連続）")
def show_bulk_add_dialog():
    default_str = st.session_state.get("bulk_default_date")  
    if default_str:
        default_date = datetime.strptime(default_str, "%Y-%m-%d").date()
    else:
        default_date = date.today()

    mode = st.radio("日付の選び方", ["単日", "連続（期間）"], horizontal=True)

    selected_dates: list[date] = []

    if mode == "単日":
        d = st.date_input("日付", value=default_date)  
        selected_dates = [d]
    else:
        st.caption("開始日〜終了日までを毎日追加します")
        start_d = st.date_input("開始日", value=default_date, key="bulk_start")  
        end_d = st.date_input("終了日", value=default_date + timedelta(days=3), key="bulk_end")  
        if start_d <= end_d:
            cur = start_d
            while cur <= end_d:
                selected_dates.append(cur)
                cur += timedelta(days=1)


    st.divider()

    # --- 予定内容 ---
    all_day = st.checkbox("終日", value=False)

    cat_labels = ["class（授業）", "job（就活）", "private（遊び）", "work（確定バイト）", "proposal（提案シフト）"]
    cat_map = {
        "class（授業）": "class",
        "job（就活）": "job",
        "private（遊び）": "private",
        "work（確定バイト）": "work",
        "proposal（提案シフト）": "proposal",
    }
    category_ui = st.selectbox("種別", cat_labels)

    start_time = end_time = None
    if not all_day:
        col1, col2 = st.columns(2)
        st_val = col1.time_input("開始", value=_t("18:00"))
        et_val = col2.time_input("終了", value=_t("22:00"))
        start_time = st_val.strftime("%H:%M")
        end_time = et_val.strftime("%H:%M")

    title = st.text_input("タイトル", placeholder="例：サンマルク")
    place = st.text_input("場所・店名（任意）")

    if st.button("まとめて追加", use_container_width=True):
        if not selected_dates:
            st.error("日付を選択してください")
            return
        if not title.strip():
            st.error("タイトルを入力してください")
            return
        if (start_time is not None) and (end_time is not None) and start_time >= end_time:
            st.error("開始 < 終了 にしてください")
            return

        cnt = 0
        for d in selected_dates:
            add_event(
                d.strftime("%Y-%m-%d"),
                start_time,
                end_time,
                cat_map[category_ui],
                title.strip(),
                place.strip() or None,
            )
            cnt += 1

        st.session_state["cal_gen"] = st.session_state.get("cal_gen", 0) + 1
        st.session_state["skip_next_dateclick"] = True
        st.session_state.pop("bulk_default_date", None)
        st.success(f"{cnt}件追加しました")
        st.rerun()



@st.dialog("予定を編集")
def show_edit_event_dialog(ev: dict):
    # ev: {"id","date","start","end","category","title","place"}
    st.write(f"🛠 **{ev['date']}** の予定を編集")

    all_day_default = (ev["start"] is None or ev["end"] is None)
    all_day = st.checkbox("終日", value=all_day_default, key=f"edit_all_day_{ev['id']}")

    cat_labels = ["class（授業）", "job（就活）", "private（遊び）", "work（確定バイト）", "proposal（提案シフト）"]
    cat_map = {
        "class（授業）": "class",
        "job（就活）": "job",
        "private（遊び）": "private",
        "work（確定バイト）": "work",
        "proposal（提案シフト）": "proposal",
    }
    rev_map = {v: k for k, v in cat_map.items()}

    with st.form(f"edit_form_{ev['id']}"):
        new_date = st.date_input("日付", value=datetime.strptime(ev["date"], "%Y-%m-%d").date())
        category_ui = st.selectbox(
            "種別",
            cat_labels,
            index=cat_labels.index(rev_map.get(ev["category"], cat_labels[0])),
        )

        start_time = end_time = None
        if not all_day:
            col1, col2 = st.columns(2)
            st_default = _t(ev["start"]) if ev["start"] else _t("10:00")
            et_default = _t(ev["end"]) if ev["end"] else _t("12:00")
            st_val = col1.time_input("開始", value=st_default, key=f"edit_st_{ev['id']}")
            et_val = col2.time_input("終了", value=et_default, key=f"edit_et_{ev['id']}")
            start_time = st_val.strftime("%H:%M")
            end_time = et_val.strftime("%H:%M")

        title = st.text_input("タイトル", value=ev["title"], key=f"edit_title_{ev['id']}")
        place = st.text_input("場所・店名", value=ev["place"] or "", key=f"edit_place_{ev['id']}")

        c1, c2, c3 = st.columns([2, 2, 2])
        save = c1.form_submit_button("保存", use_container_width=True)
        delete = c2.form_submit_button("削除", use_container_width=True)
        cancel = c3.form_submit_button("キャンセル", use_container_width=True)

        if cancel:
            st.session_state["skip_next_dateclick"] = True
            st.rerun()

        if delete:
            delete_event(int(ev["id"]))
            st.session_state["cal_gen"] = st.session_state.get("cal_gen", 0) + 1
            st.session_state["skip_next_dateclick"] = True
            st.rerun()

        if save:
            if not title.strip():
                st.error("タイトルを入力してください")
                return
            if (start_time is not None) and (end_time is not None) and start_time >= end_time:
                st.error("開始 < 終了 にしてください")
                return

            update_event(
                int(ev["id"]),
                new_date.strftime("%Y-%m-%d"),
                start_time,
                end_time,
                cat_map[category_ui],
                title.strip(),
                place.strip() or None,
            )
            st.session_state["cal_gen"] = st.session_state.get("cal_gen", 0) + 1
            st.session_state["skip_next_dateclick"] = True
            st.rerun()



# ---------- main ----------
st.set_page_config(page_title="バイトシフト作成", layout="wide")
init_db()

st.title("📅 バイトシフト作成アプリ")

today = date.today()

if "year" not in st.session_state:
    st.session_state["year"] = today.year
if "month" not in st.session_state:
    st.session_state["month"] = today.month

c1, c2 = st.columns(2)

c1.number_input("年", 2020, 2035, step=1, key="year")
c2.number_input("月", 1, 12, step=1, key="month")

year = int(st.session_state["year"])
month = int(st.session_state["month"])



ym_key = f"{year}-{month:02d}"
if st.session_state.get("ym_key") != ym_key:
    st.session_state["ym_key"] = ym_key
    st.session_state["skip_next_dateclick"] = True

# ---------- Sidebar: shift proposal ----------
st.sidebar.header("🧠 シフト提案")

# 上限
st.sidebar.subheader("上限設定")
max_day, max_week = get_settings()
new_max_day = st.sidebar.number_input("1日上限（時間）", 0, 24, max_day, 1)
new_max_week = st.sidebar.number_input("週上限（時間）", 0, 80, max_week, 1)
if st.sidebar.button("上限を保存", use_container_width=True):
    upsert_settings(int(new_max_day), int(new_max_week))
    st.sidebar.success("保存しました")

# 時給
st.sidebar.subheader("時給設定")
wages = get_wages()
wp = st.sidebar.selectbox("バイト先", ["サンマルク", "成城石井"])
w0 = wages.get(wp, 1100)
wage_val = st.sidebar.number_input("時給（円）", 0, 10000, int(w0), 1)
if st.sidebar.button("時給を保存", use_container_width=True):
    upsert_wage(wp, int(wage_val))
    st.sidebar.success("保存しました")

# ✅ A案：提案に使う曜日（ON/OFFだけ）
st.sidebar.subheader("提案に使う曜日（ON/OFF）")
DOW_LABELS = ["月", "火", "水", "木", "金", "土", "日"]

# 初期化（全部ON）
if "avail_days" not in st.session_state:
    st.session_state["avail_days"] = {
        "サンマルク": [True] * 7,
        "成城石井": [True] * 7,
    }

wp2 = st.sidebar.selectbox("バイト先（曜日設定）", ["サンマルク", "成城石井"], key="avail_wp")
days = st.session_state["avail_days"][wp2]

for i, lab in enumerate(DOW_LABELS):
    days[i] = st.sidebar.checkbox(lab, value=days[i], key=f"avail_{wp2}_{i}")

st.session_state["avail_days"][wp2] = days


# 提案生成
st.sidebar.subheader("今月の提案")

# 別案用seed
if "proposal_seed" not in st.session_state:
    st.session_state["proposal_seed"] = 0

first, last = month_range(year, month)
st.sidebar.write(f"対象：{first.strftime('%Y-%m')}（{first}〜{last}）")

cA, cB = st.sidebar.columns(2)
if cA.button("別案", use_container_width=True):
    st.session_state["proposal_seed"] += 1
if cB.button("seedリセット", use_container_width=True):
    st.session_state["proposal_seed"] = 0

if st.sidebar.button("今月の提案を作成", use_container_width=True):
    wages = get_wages()
    max_day, max_week = get_settings()

    if not wages:
        st.sidebar.error("時給が未登録です")
    else:
        start_s = first.strftime("%Y-%m-%d")
        end_s = last.strftime("%Y-%m-%d")

        delete_proposals_in_range(start_s, end_s)
        events_month = fetch_events_between(start_s, end_s)

        total_h = 0
        total_income = 0

        for wi, ws in enumerate(iter_week_starts_in_month(year, month)):
            picked = propose_week_fixed_slots(
                week_start_date=ws,
                max_day=max_day,
                max_week=max_week,
                wages=wages,
                events=events_month,
                seed=st.session_state["proposal_seed"] + wi * 101,
                avail_days=st.session_state["avail_days"],
            )

            for p in picked:
                pd = datetime.strptime(p["date"], "%Y-%m-%d").date()
                if pd < first or pd > last:
                    continue

                add_event(p["date"], p["start"], p["end"], "proposal",  p["workplace"], p["workplace"])

                # proposal同士も衝突扱いにするため追加
                events_month.append({
                    "id": -1,
                    "date": p["date"],
                    "start": p["start"],
                    "end": p["end"],
                    "category": "proposal",
                    "title":  p["workplace"],
                    "place": p["workplace"],
                })

                total_h += p["hours"]
                total_income += p["income"]

        st.sidebar.success(f"作成：{total_h}時間 / {total_income:,}円（seed={st.session_state['proposal_seed']}）")
        st.session_state["cal_gen"] = st.session_state.get("cal_gen", 0) + 1
        st.session_state["skip_next_dateclick"] = True
        st.rerun()


if st.sidebar.button("今月の提案を確定（workへ）", use_container_width=True):
    convert_proposals_to_work(first.strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d"))
    st.sidebar.success("確定しました（proposal→work）")
    st.session_state["cal_gen"] = st.session_state.get("cal_gen", 0) + 1
    st.session_state["skip_next_dateclick"] = True
    st.rerun()

st.sidebar.subheader("🗑 提案シフトの管理")

if st.sidebar.button("今月の提案シフトを一括削除", use_container_width=True):
    delete_proposals_in_range(
        first.strftime("%Y-%m-%d"),
        last.strftime("%Y-%m-%d"),
    )
    st.sidebar.success("今月の提案シフトをすべて削除しました")
    st.session_state["cal_gen"] = st.session_state.get("cal_gen", 0) + 1
    st.session_state["skip_next_dateclick"] = True
    st.rerun()


events_by_date = fetch_events_in_month(year, month)

# =========================
# 📊 集計（proposal / work）
# events_by_date を作った直後に置く
# =========================

# 1) 月のイベントを平坦化
flat = [ev for evs in events_by_date.values() for ev in evs]

def build_shift_dataframe(events, category: str):
    wages = get_wages()  
    rows = []

    for ev in events:
        if ev.get("category") != category:
            continue
        if not ev.get("start") or not ev.get("end"):
            continue

        wp = ev.get("place") or ev.get("title") or "不明"  
        d = ev["date"]
        s = ev["start"]
        e = ev["end"]

        mins = int(
            (
                datetime.strptime(f"{d} {e}", "%Y-%m-%d %H:%M")
                - datetime.strptime(f"{d} {s}", "%Y-%m-%d %H:%M")
            ).total_seconds() // 60
        )
        hours = mins / 60.0
        income = hours * wages.get(wp, 0)

        rows.append({
            "date": d,
            "workplace": wp,
            "start": s,
            "end": e,
            "hours": hours,
            "income": int(income),
        })

    return pd.DataFrame(rows)

# 2) proposal と work を両方作る
df_proposal = build_shift_dataframe(flat, "proposal")
df_work = build_shift_dataframe(flat, "work")

# 3) 表示
st.subheader("📊 集計（この月）")

# --- 提案 ---
st.markdown("### 🧠 提案シフト（proposal）")
if df_proposal.empty:
    st.info("この月の提案シフト（proposal）がありません。")
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("件数", f"{len(df_proposal)} 件")
    c2.metric("合計労働時間", f"{df_proposal['hours'].sum():.1f} h")
    c3.metric("合計収入(概算)", f"{df_proposal['income'].sum():,} 円")

    with st.expander("店別内訳（proposal）"):
        st.dataframe(
            df_proposal.groupby("workplace")[["hours", "income"]]
            .sum()
            .reset_index(),
            use_container_width=True,
        )

# --- 確定 ---
st.markdown("### ✅ 確定シフト（work）")
if df_work.empty:
    st.info("この月の確定シフト（work）がありません。")
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("件数", f"{len(df_work)} 件")
    c2.metric("合計労働時間", f"{df_work['hours'].sum():.1f} h")
    c3.metric("合計収入(確定)", f"{df_work['income'].sum():,} 円")

    with st.expander("店別内訳（work）"):
        st.dataframe(
            df_work.groupby("workplace")[["hours", "income"]]
            .sum()
            .reset_index(),
            use_container_width=True,
        )

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

        item = {
            "id": str(ev["id"]),
            "title": format_event_label(ev),
            "start": start,
            "end": end,
            "allDay": all_day_flag,
        }

        # proposalは店名(place)で色分け
        if ev["category"] == "proposal":
            if ev["place"] == "サンマルク":
                item["backgroundColor"] = "#FFCC80"
                item["borderColor"] = "#FB8C00"
                item["textColor"] = "#000000"
            elif ev["place"] == "成城石井":
                item["backgroundColor"] = "#FC7B71F5"
                item["borderColor"] = "#CB886E"
                item["textColor"] = "#000000"

        fc_events.append(item)


calendar_options = {
    "initialView": "dayGridMonth",
    "locale": "ja",
    "height": 650,
    "initialDate": f"{year}-{month:02d}-01",
    "timeZone": "Asia/Tokyo",
    "displayEventTime": False,
    "dayMaxEvents": True,
    "eventDisplay": "block",
    "headerToolbar": {
        "left": "",
        "center": "title",
        "right": "",
    },

}

cal_gen = st.session_state.get("cal_gen", 0)
state = st_calendar(
    events=fc_events,
    options=calendar_options,
    callbacks=["dateClick", "eventClick", "datesSet"],
    key=f"calendar_{year}_{month}_{cal_gen}",
)

if state and state.get("datesSet"):
    ds = state["datesSet"]

    # 1) まず view.title を試す（例: "2026年2月" みたいな文字）
    title = ""
    if isinstance(ds, dict):
        view = ds.get("view") or {}
        if isinstance(view, dict):
            title = view.get("title") or ""

    if title:
        m = re.search(r"(\d{4}).*?(\d{1,2})", title)
        if m:
            new_y = int(m.group(1))
            new_m = int(m.group(2))
            if (new_y, new_m) != (st.session_state.get("year"), st.session_state.get("month")):
                st.session_state["year"] = new_y
                st.session_state["month"] = new_m
                st.session_state["skip_next_dateclick"] = True
                st.rerun()
    else:
        start_str = (ds.get("startStr") or ds.get("start") or "")[:10]
        if start_str:
            y, mth, _ = map(int, start_str.split("-"))
            dt = date(y, mth, 1) + timedelta(days=10)
            new_y, new_m = dt.year, dt.month
            if (new_y, new_m) != (st.session_state.get("year"), st.session_state.get("month")):
                st.session_state["year"] = new_y
                st.session_state["month"] = new_m
                st.session_state["skip_next_dateclick"] = True
                st.rerun()


if st.session_state.get("skip_next_dateclick", False):
    st.session_state["skip_next_dateclick"] = False
else:
    if state and state.get("eventClick"):
        ec = state["eventClick"]

        event_id = None
        if isinstance(ec, dict):
            event_id = (ec.get("event", {}) or {}).get("id") or ec.get("id")

        if event_id is not None:
            target = fetch_event_by_id(int(event_id))
            if target:
                show_edit_event_dialog(target)
            else:
                st.warning("この予定が見つかりませんでした")
            st.stop()  

    if state and state.get("dateClick"):
        dc = state["dateClick"]
        raw = dc.get("dateStr") or dc.get("date") or ""
        clicked_date = raw[:10]

        try:
            y, m, d = map(int, clicked_date.split("-"))
            if y != int(year) or m != int(month):
                clicked_date = f"{int(year):04d}-{int(month):02d}-{d:02d}"
        except Exception:
            pass

        st.session_state["bulk_default_date"] = clicked_date  
        show_bulk_add_dialog()

st.divider()
st.subheader("🗂 この月の予定一覧（削除）")

flat = [ev for evs in events_by_date.values() for ev in evs]
flat.sort(key=lambda x: (x["date"], x["start"] or "99:99", x["id"]))

if not flat:
    st.info("この月の予定はまだありません。予定を追加してね")
else:
    for i, ev in enumerate(flat):
        with st.container(border=True):
            c1, c2 = st.columns([8, 1], vertical_alignment="center")

            label = f"{ev['date']} | {format_event_label(ev)} | [{ev['category']}]"
            if ev.get("place"):
                label += f" ＠{ev['place']}"
            c1.markdown(label)

            
            if c2.button("削除", key=f"del_{ev['id']}_{i}", use_container_width=True):
                delete_event(int(ev["id"]))
                st.session_state["cal_gen"] = st.session_state.get("cal_gen", 0) + 1
                st.session_state["skip_next_dateclick"] = True
                st.rerun()
