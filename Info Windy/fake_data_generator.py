#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Fake Time-Series File Generator (Wind Station style) — Chained by default
-------------------------------------------------------------------------
• Lit un template OU reprend depuis le dernier fichier de --out (chaînage).
• À chaque itération : écrit un NOUVEAU fichier = (toutes les lignes précédentes + 1).
• Gère timestamps en 1 colonne ou en 2 colonnes (Date, Heure).
• Pas de microsecondes, 1 décimale, séparateur homogène.
Commande à copier dans le terminal python fake_data_generator.py --template "GP2 03-12-24_07-30-33.txt"
"""


import argparse
import io
import re
import sys
import time
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import requests


# ------------------ helpers format ------------------

def _round_numeric_df(df, ndigits=1):
    df2 = df.copy()
    for c in df2.columns:
        s = pd.to_numeric(df2[c], errors='coerce')
        if s.notna().sum() > 0:
            if str(df2[c].dtype).startswith('datetime'):
                continue
            m = s.notna()
            s[m] = np.round(s[m].astype(float), ndigits)
            df2[c] = s.where(m, df2[c])
    return df2


def _extract_timestamp_from_name(name):
    m = re.search(r'(\d{2}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})', name)
    if not m:
        return None
    ds, ts = m.group(1), m.group(2)
    try:
        return datetime.strptime(f"{ds}_{ts}", "%d-%m-%y_%H-%M-%S")
    except Exception:
        return None


def _find_latest_file(out_dir):
    out = Path(out_dir)
    if not out.exists():
        return None
    best = None
    best_t = None
    for f in out.glob("*.txt"):
        if not f.is_file():
            continue
        t = _extract_timestamp_from_name(f.name)
        if t is not None and (best_t is None or t > best_t):
            best_t = t
            best = f
    return best


def sniff_dialect(text):
    # Détecte décimale et séparateur
    lines = text.splitlines()[:50]
    decimal = '.'
    comma_count = dot_count = 0
    for ln in lines:
        if re.search(r"[A-Za-z]", ln) and not re.search(r"\d", ln):
            continue
        comma_count += ln.count(',')
        dot_count += ln.count('.')
    if comma_count > dot_count and comma_count > 0:
        decimal = ','

    seps = ['\t', ';', ',', None]  # None => regex \s+
    sep_scores = {}
    for s in seps:
        try:
            df_try = pd.read_csv(io.StringIO(text),
                                 sep=s if s is not None else r"\s+",
                                 engine='python',
                                 nrows=25,
                                 decimal=decimal)
            sep_scores[s if s is not None else r"\s+"] = df_try.shape[1]
        except Exception:
            sep_scores[s if s is not None else r"\s+"] = -1

    best_sep = max(sep_scores, key=lambda k: sep_scores[k])

    # IMPORTANT : si l’entrée est à espaces (r"\s+"), on forcera la sortie à **un seul espace**
    if best_sep == r"\s+":
        sep = r"\s+"
        out_sep = ' '            # <-- plus de tab ici
    else:
        sep = best_sep
        out_sep = best_sep

    # Header (1 ou 2 lignes)
    header_lines = 0
    try:
        df1 = pd.read_csv(io.StringIO(text), sep=sep, engine='python', nrows=100, decimal=decimal, header=0)
        if df1.columns.duplicated().any():
            raise ValueError
        header_lines = 1
    except Exception:
        pass
    if header_lines == 0:
        try:
            df2 = pd.read_csv(io.StringIO(text), sep=sep, engine='python', nrows=100, decimal=decimal, header=[0,1])
            flat_cols = [f"{str(a).strip()}__{str(b).strip()}" if str(b).strip() and str(b).strip() != 'nan' else str(a).strip()
                         for a, b in df2.columns.to_list()]
            if len(set(flat_cols)) == len(flat_cols):
                header_lines = 2
        except Exception:
            pass
    if header_lines == 0:
        header_lines = 1

    return decimal, sep, out_sep, header_lines


def read_template(path):
    txt = Path(path).read_text(encoding='utf-8', errors='ignore')
    decimal, sep, out_sep, header_lines = sniff_dialect(txt)

    if header_lines == 2:
        df = pd.read_csv(io.StringIO(txt), sep=sep, engine='python', decimal=decimal, header=[0,1])
        col_tuples = df.columns.to_list()
        top = [str(a).strip() for a, _ in col_tuples]
        bot = [str(b).strip() for _, b in col_tuples]
        first_col_label = top[0]
        flat_cols = []
        for a, b in col_tuples:
            a = str(a).strip(); b = str(b).strip()
            flat_cols.append(f"{a}__{b}" if b and b != 'nan' else a)
        df.columns = flat_cols
        meta = dict(decimal=decimal, sep=sep, out_sep=out_sep, header_lines=2,
                    top=top, bot=bot, first_col_label=first_col_label)
    else:
        df = pd.read_csv(io.StringIO(txt), sep=sep, engine='python', decimal=decimal, header=0)
        first_col_label = df.columns[0]
        meta = dict(decimal=decimal, sep=sep, out_sep=out_sep, header_lines=1,
                    header=df.columns.tolist(), first_col_label=first_col_label)

    return df, meta


# ------------------ gestion robuste du temps ------------------

DATE_RX = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$")
TIME_RX = re.compile(r"^\s*\d{1,2}:\d{2}:\d{2}\s*$")

def detect_time_schema(df, meta):
    cols = list(df.columns)
    if len(cols) >= 2:
        s1 = str(df[cols[0]].dropna().astype(str).head(1).iloc[0]) if df[cols[0]].notna().any() else ""
        s2 = str(df[cols[1]].dropna().astype(str).head(1).iloc[0]) if df[cols[1]].notna().any() else ""
        if DATE_RX.match(s1) and TIME_RX.match(s2):
            return {"mode": "split", "date_col": cols[0], "time_col": cols[1]}
    return {"mode": "single", "col": cols[0]}


def get_time_series(df, schema):
    if schema["mode"] == "single":
        return pd.to_datetime(df[schema["col"]], dayfirst=True, errors='coerce')
    d = df[schema["date_col"]].astype(str).str.strip()
    h = df[schema["time_col"]].astype(str).str.strip()
    combo = (d + " " + h).str.replace(r"\s+", " ", regex=True)
    return pd.to_datetime(combo, dayfirst=True, errors='coerce')


def set_last_time_in_df(df, schema, dt):
    if schema["mode"] == "single":
        # Forcer un format sans microsecondes
        df.loc[df.index[-1], schema["col"]] = pd.Timestamp(dt).strftime("%d/%m/%Y %H:%M:%S")
    else:
        df.loc[df.index[-1], schema["date_col"]] = pd.Timestamp(dt).strftime("%d/%m/%Y")
        df.loc[df.index[-1], schema["time_col"]] = pd.Timestamp(dt).strftime("%H:%M:%S")


def infer_period(ts):
    ts = ts.dropna()
    if len(ts) >= 3:
        d = (ts.iloc[-1] - ts.iloc[-2]).total_seconds()
        if d > 0:
            return int(d)
    return 60


def next_coherent_time(ts):
    period = infer_period(ts)
    now = pd.Timestamp(datetime.now())
    candidate = ts.iloc[-1] + pd.Timedelta(seconds=period)
    return (now if now > candidate else candidate).to_pydatetime()


# ------------------ génération nouvelle ligne ------------------

def generate_next_row(df, meta):
    schema = detect_time_schema(df, meta)
    ts = get_time_series(df, schema).dropna()
    period = infer_period(ts)
    next_time = ts.iloc[-1] + pd.Timedelta(seconds=period)

    new_row = {}
    for col in df.columns:
        base = str(col).split('__')[0]
        if schema["mode"] == "single" and col == schema["col"]:
            new_row[col] = next_time
            continue
        if schema["mode"] == "split" and col in (schema["date_col"], schema["time_col"]):
            new_row[col] = df[col].iloc[-1]  # provisoire, on formate à l'écriture
            continue

        ser = pd.to_numeric(df[col], errors='coerce')
        if ser.notna().sum() == 0:
            new_row[col] = df[col].iloc[-1]
            continue

        last = ser.iloc[-1]
        recent = ser.dropna().tail(10)
        sigma = recent.std() if recent.size >= 2 else (abs(last) * 0.02 if last != 0 else 0.1)
        if not np.isfinite(sigma) or sigma == 0:
            sigma = abs(last) * 0.02 if last != 0 else 0.1
        noise = np.random.normal(0, sigma * 0.3)
        val = last + noise
        if np.isfinite(sigma) and sigma > 0:
            val = float(np.clip(val, last - 3*sigma, last + 3*sigma))
        name_low = base.lower()
        if 'dir' in name_low:
            val = (val % 360 + 360) % 360
        if 'rh' in name_low or 'humid' in name_low:
            val = float(np.clip(val, 0, 100))
        new_row[col] = float(np.round(val, 1))

    return pd.Series(new_row)


# ------------------ écriture contrôlée (pas de tab) ------------------

def _format_val(v, dec):
    if isinstance(v, (int, np.integer)):
        return str(v)
    if isinstance(v, (float, np.floating)):
        s = f"{v:.1f}"
        return s.replace('.', ',') if dec == ',' else s
    return str(v)


# --- Instead of writing files, POST the latest row to backend ---
def post_row_to_backend(row, meta, station="GP2", backend_url="http://localhost:5000/api/gp2_data"):
    # Prepare row as dict (with rounded values)
    dec = meta['decimal']
    row_dict = {k: _format_val(v, dec) for k, v in row.items()}
    row_dict['station'] = station
    try:
        resp = requests.post(backend_url, json=row_dict, timeout=5)
        if resp.status_code == 200:
            print(f"[POST] Sent row to backend: {row_dict}")
        else:
            print(f"[POST] Error {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[POST] Exception: {e}")


# ------------------ main (chaînage par dernier fichier) ------------------


    ap = argparse.ArgumentParser(description="Generate fake time-series rows and POST to backend.")
    ap.add_argument("--template", required=True, help="Path to a sample data file (.txt/.csv)")
    ap.add_argument("--station", default="GP2", help="Station name to embed in row")
    ap.add_argument("--interval", type=int, default=60, help="Seconds between rows (default 60)")
    ap.add_argument("--simulate", type=int, default=0, help="If >0, create N rows then exit")
    ap.add_argument("--seed", type=int, default=None, help="Optional RNG seed for reproducibility")
    ap.add_argument("--backend-url", default="http://localhost:5000/api/gp2_data", help="Backend API URL to POST rows")
    args = ap.parse_args()

    if args.seed is not None:
        np.random.seed(args.seed)

    df, meta = read_template(str(args.template))
    schema = detect_time_schema(df, meta)
    ts = get_time_series(df, schema)
    df = df[ts.notna()].reset_index(drop=True)
    if df.empty:
        print("No parsable data rows.", file=sys.stderr)
        sys.exit(2)

    # First new row
    new_row = generate_next_row(df, meta)
    post_row_to_backend(new_row, meta, station=args.station, backend_url=args.backend_url)
    df_next = pd.concat([df, new_row.to_frame().T], ignore_index=True)

    # Loop: each iteration, generate new row and POST
    count = args.simulate - 1 if args.simulate > 0 else -1
    while True:
        if args.simulate > 0 and count <= 0:
            break
        time.sleep(args.interval)

        df, meta = read_template(str(args.template))
        schema = detect_time_schema(df, meta)
        ts = get_time_series(df, schema)
        df = df[ts.notna()].reset_index(drop=True)
        # Add all previously generated rows
        df_next = pd.concat([df_next, new_row.to_frame().T], ignore_index=True)

        new_row = generate_next_row(df_next, meta)
        post_row_to_backend(new_row, meta, station=args.station, backend_url=args.backend_url)
        # Update buffer
        df_next = pd.concat([df_next, new_row.to_frame().T], ignore_index=True)

        if args.simulate > 0:
            count -= 1


if __name__ == "__main__":
    main()
