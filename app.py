"""PPE Model Evaluation Viewer · evidence-first, read-only Streamlit app.

All predictions are loaded from saved CSV files. No live Ollama calls are made.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

from evaluation import (
    DATASETS, SCOPES, evidence_rows, full_image_rows, ground_truth, metrics,
    model_runs, outcome, prediction, read_csv, reviewed_images,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

st.set_page_config(
    page_title="PPE · Model Evaluation",
    page_icon="🦺",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container {padding-top: 5rem; max-width: 1580px;}
    div[data-testid="stMetric"] {background:#fff;border:1px solid #e4e9f2;
       border-radius: 12px;padding: 12px 15px;min-height:110px;}
    div[data-testid="stMetricLabel"] {color:#64748b;}
    div[data-testid="stMetricValue"] {color:#17253b;}
    .mini-kicker{letter-spacing:1.8px;color:#11765f;font-size:12px;font-weight:800;}
    .muted-note{color:#64748b;font-size:13px;line-height:1.5;}
    .result-chip{display:inline-block;padding:3px 9px;border-radius:7px;font-size:12px;
       font-weight:750;margin-right:6px;}
    .chip-TP,.chip-TN{background:#dcfce7;color:#166534;}
    .chip-FP,.chip-FN{background:#fee2e2;color:#991b1b;}
    .chip-Unclear,.chip-Error{background:#fef3c7;color:#92400e;}
    .chip-other{background:#edf2f7;color:#475569;}
    .conf-cell{border:1px solid #e1e8ed;padding:16px;border-radius:11px;
       background:#fff;text-align:center;margin-bottom:7px;}
    .conf-num{font-size:27px;font-weight:800;}
    .gtline {font-size:12px;color:#596a7f;}
</style>
""", unsafe_allow_html=True)


def pct(number):
    return "N/A" if number is None else f"{number * 100:.1f}%"


def count_fmt(number):
    return "—" if number is None else f"{number:,}"


def seconds_fmt(value):
    try:
        return f"{float(value):.2f} s"
    except (TypeError, ValueError):
        return "—"


def chip(label):
    color_key = label if label in {"TP", "TN", "FP", "FN", "Unclear", "Error"} else "other"
    return f'<span class="result-chip chip-{color_key}">{label}</span>'


def image_file(dataset_dir, image_name):
    candidate = dataset_dir / "images" / Path(image_name).name
    return candidate if candidate.is_file() else None


def image_render(dataset_dir, image_name, *, caption=None):
    img = image_file(dataset_dir, image_name)
    if img:
        st.image(str(img), caption=caption, use_container_width=True)
    else:
        st.warning(f"Image unavailable: {Path(image_name).name}")


def show_ppe_detail(label, pred, items):
    table = []
    for item in items:
        truth = label.get(f"verified_{item}", "") or "unclear"
        response = (pred or {}).get(f"pred_{item}", "") or ("Not evaluated" if pred is None else "error")
        result = outcome(truth.lower(), response.lower() if response != "Not evaluated" else "missing", item)
        table.append({"PPE item": SCOPES[item], "Ground truth": truth,
                      "Model prediction": response, "Outcome": result})
    st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)
    if pred:
        a, b = st.columns(2)
        a.markdown(f"**Model worker count:** {pred.get('pred_worker_count') or 'Not provided'}")
        b.markdown(f"**Processing time:** {seconds_fmt(pred.get('seconds'))}")
        if pred.get("error"):
            st.error(str(pred["error"]))
        with st.expander("Model's original response (JSON/text)"):
            raw = (pred.get("raw_response") or "").strip()
            try:
                st.json(json.loads(raw))
            except (ValueError, TypeError):
                st.code(raw or "No response text was produced.", language="text")


def top_metrics(rows):
    m = metrics(rows)
    tiles = [
        ("Accuracy", pct(m["accuracy"])),
        ("Precision", pct(m["precision"])),
        ("Recall", pct(m["recall"])),
        ("F1-score", pct(m["f1"])),
        ("Coverage", pct(m["coverage"])),
        ("Avg. request time", seconds_fmt(sum(float(r["model_row"].get("seconds") or 0) for r in rows if r["model_row"]) / m["attempted"] if m["attempted"] else None)),
    ]
    columns = st.columns(6)
    for col, (name, value) in zip(columns, tiles):
        col.metric(name, value)
    st.caption("Metrics use only decisive predictions with binary ground truth. Unclear and error outcomes reduce coverage, not ordinary accuracy. Request time includes model execution/transport.")
    return m


def matrix(m):
    st.markdown("**Confusion matrix** · violation is the positive class")
    with st.container(border=True):
        st.caption("Rows = actual ground truth · Columns = model prediction")
        left, right = st.columns(2)
        with left:
            st.markdown(f'<div class="conf-cell"><div class="gtline">ACTUAL VIOLATION · PREDICTED VIOLATION</div><div class="conf-num" style="color:#147d55">{m["tp"]}</div><div class="gtline">True positives · correctly detected</div></div>', unsafe_allow_html=True)
        with right:
            st.markdown(f'<div class="conf-cell"><div class="gtline">ACTUAL VIOLATION · PREDICTED COMPLIANT</div><div class="conf-num" style="color:#b42318">{m["fn"]}</div><div class="gtline">False negatives · missed violations</div></div>', unsafe_allow_html=True)
        left, right = st.columns(2)
        with left:
            st.markdown(f'<div class="conf-cell"><div class="gtline">ACTUAL COMPLIANT · PREDICTED VIOLATION</div><div class="conf-num" style="color:#b42318">{m["fp"]}</div><div class="gtline">False positives · unnecessary alerts</div></div>', unsafe_allow_html=True)
        with right:
            st.markdown(f'<div class="conf-cell"><div class="gtline">ACTUAL COMPLIANT · PREDICTED COMPLIANT</div><div class="conf-num" style="color:#147d55">{m["tn"]}</div><div class="gtline">True negatives · correctly cleared</div></div>', unsafe_allow_html=True)
    st.caption(f"Decisive: {m['decisive']} · Errors: {m['errors']} · Unclear: {m['unclear']} · Unscored ground truth: {m['unscored_truth']}")


def evidence_selector(rows, model, scope, target_status=None):
    options = [r["image"] for r in rows]
    if not options:
        return None
    label_map = {r["image"]: r for r in rows}
    q = st.selectbox("Choose an image", options, format_func=lambda x: f"{x[:42]}… · {label_map[x]['outcome']}" if len(x)>42 else f"{x} · {label_map[x]['outcome']}", key=f"image_selector_{model}_{scope}")
    return label_map[q]


def show_image_detail(record, dataset_dir, items, model):
    st.divider()
    st.subheader("Image evidence")
    st.caption(record["image"])
    img_column, detail_column = st.columns([1.15, 1], gap="large")
    with img_column:
        image_render(dataset_dir, record["image"])
    with detail_column:
        st.markdown(chip(record["outcome"]), unsafe_allow_html=True)
        st.markdown(f"**Ground truth:** `{record['truth']}`")
        st.markdown(f"**{model} prediction:** `{record['prediction']}`")
        st.markdown("**Helmet / vest / boots breakdown**")
        show_ppe_detail(record["label_row"], record["model_row"], items)
        notes = record["label_row"].get("notes", "").strip()
        if notes:
            st.info("Reviewer note: " + notes)


@st.dialog("PPE Image Inspection", width="large")
def inspect_image_dialog(record, dataset_dir, items, model):
    show_image_detail(record, dataset_dir, items, model)

    if st.button("Close inspection", key="close_inspection"):
        st.rerun()


def truth_summary(labels, items):
    st.subheader("Verified dataset · Ground-truth distribution")
    rows = []
    for item in items:
        counts = Counter((r.get(f"verified_{item}") or "").lower() for r in labels)
        rows.append({"PPE": SCOPES[item], "Violations (yes)":counts["yes"],
                     "No violation (no)":counts["no"], "Unclear":counts["unclear"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption("yes = confirmed visible violation; no = no visible violation under the benchmark's PPE requirement; unclear = not sufficiently assessable. Footwear certification cannot be verified from an image.")


def explorer(records, dataset_dir, labels, items, model, scope, *, gallery_only=False):
    st.markdown('<p class="mini-kicker">IMAGE-LEVEL EVIDENCE</p>', unsafe_allow_html=True)
    st.subheader("Find the photographs behind the metrics")
    outcomes = sorted({r["outcome"] for r in records})
    c1, c2, c3 = st.columns([1.2, 1, 1])
    with c1:
        defaults = [x for x in ("FP", "FN", "Error") if x in outcomes] if not gallery_only else []
        selected_outcomes = st.multiselect("Filter results", outcomes, default=defaults, key=f"outcomes_{model}_{scope}_{gallery_only}")
    with c2:
        search = st.text_input("Find filename", placeholder="Search image names", key=f"search_{model}_{scope}_{gallery_only}")
    with c3:
        truth_choice = st.selectbox("Actual label", ["All", "violation", "compliant", "yes", "no", "unclear"], key=f"actual_{model}_{scope}_{gallery_only}")
    filtered = [r for r in records if (not selected_outcomes or r["outcome"] in selected_outcomes)
                and search.lower() in r["image"].lower()
                and (truth_choice == "All" or r["truth"] == truth_choice)]
    filtered.sort(key=lambda r: ({"FN":0, "FP":1, "Error":2, "Unclear":3, "TP":4, "TN":5}.get(r["outcome"],6), r["image"]))
    st.caption(f"Showing {len(filtered)} of {len(records)} image records. TP/TN = correct; FP = false alert; FN = missed violation.")
    if not filtered:
        st.info("No images match these filters. Try clearing the result filter.")
        return

    focus = next(r for r in filtered if r["image"] == st.session_state[gallery_key])
    show_image_detail(focus, dataset_dir, items, model)

    st.divider()
    st.markdown("**Browse image gallery** · click Inspect to open the full evidence")
    page_size = 9
    pages = max(1, (len(filtered)+page_size-1)//page_size)
    page = st.number_input("Gallery page", min_value=1, max_value=pages, step=1, key=f"page_{model}_{scope}_{gallery_only}")
    current=filtered[(page-1)*page_size:page*page_size]
    for idx in range(0,len(current),3):
        cols=st.columns(3, gap="medium")
        for col, row in zip(cols,current[idx:idx+3]):
            with col:
                with st.container(border=True):
                    image_render(dataset_dir,row["image"])
                    st.markdown(chip(row["outcome"]),unsafe_allow_html=True)
                    st.markdown(f"**Actual:** `{row['truth']}`  ·  **Predicted:** `{row['prediction']}`")
                    st.caption(row["image"][:61])
                    if st.button(
                        "Inspect image",
                        key=f"inspect_{model}_{scope}_{gallery_only}_{row['image']}",
                        use_container_width=True
                    ):
                        inspect_image_dialog(row, dataset_dir, items, model)



def overview(dataset_dir, labels, runs, items, scope, preferred):
    st.markdown('<p class="mini-kicker">MODEL PERFORMANCE</p>', unsafe_allow_html=True)
    st.subheader("Cross-model comparison")
    if not runs:
        st.info("There are no saved model predictions for this benchmark yet. Ground-truth images are available below. To add results, copy the `predictions_<model>.csv` files from your notebook into this dataset's `predictions` folder and refresh the app.")
        truth_summary(labels,items)
        return

    table=[]
    for model, run in runs.items():
        rr=evidence_rows(labels,run,scope,items)
        m=metrics(rr)
        times=[]
        for r in rr:
            try: times.append(float((r["model_row"] or {}).get("seconds", "")))
            except ValueError: pass
        table.append({"Model":model,"Images":m["attempted"],"Decisive":m["decisive"],
                      "Accuracy":m["accuracy"], "Precision":m["precision"], "Recall":m["recall"],
                      "F1":m["f1"],"FPR":m["false_positive_rate"],"Coverage":m["coverage"],
                      "FP":m["fp"],"FN":m["fn"],"Errors":m["errors"],"Unclear":m["unclear"],
                      "Avg. seconds":sum(times)/len(times) if times else None})
    df=pd.DataFrame(table).sort_values(by="F1",ascending=False,na_position="last")
    display=df.copy()
    for col in ("Accuracy","Precision","Recall","F1","FPR","Coverage"):
        display[col]=display[col].apply(pct)
    display["Avg. seconds"]=display["Avg. seconds"].apply(seconds_fmt)
    st.dataframe(display,hide_index=True,use_container_width=True,height=min(380, 56 + 35*len(df)))
    st.caption("Calculated from each model's saved per-image predictions. Blank/N/A means undefined (e.g., no usable classifications), not 0% accuracy. Compare only runs using the same benchmark.")
    if df["F1"].notna().any():
        st.markdown("**Performance overview**")
        chart_df=df.set_index("Model")[["Accuracy","Recall","Precision"]].dropna(how="all")*100
        st.bar_chart(chart_df, y_label="Percent (%)", height=290)
    if "dlasher/MiniCPM-V-4.7-35B-A3B:IQ4_NL" in runs:
        st.info("The dlasher 35B-A3B run had request/response failures. Its missing accuracy isn't evidence of poor PPE classification; the model did not produce usable decisions.")
    st.divider()
    st.subheader("Selected model · in-depth results")
    selected=evidence_rows(labels,runs[preferred],scope,items)
    m=top_metrics(selected)
    p,q=st.columns([1.2,1])
    with p: matrix(m)
    with q:
        st.markdown("**Where the classifications went**")
        if selected:
            counter=Counter(r["outcome"] for r in selected)
            st.bar_chart(pd.DataFrame({"Images":[counter[x] for x in ("TP","TN","FP","FN","Unclear","Error")]}, index=["TP","TN","FP","FN","Unclear","Error"]),height=280)
        st.markdown(f"**Strict accuracy:** {pct(m['strict_accuracy'])} · **Actionable recall:** {pct(m['actionable_recall'])}")
        st.caption("Strict accuracy penalises inconclusive responses. Actionable recall counts detected positives among all ground-truth positives, including uncertain/error outputs in its denominator.")
    st.subheader("Examples of real errors")
    wrong=[r for r in selected if r["outcome"] in ("FP","FN")]
    if wrong:
        wrong.sort(key=lambda r:(r["outcome"]!="FN",r["image"]))
        cols=st.columns(min(3,len(wrong)))
        for col, record in zip(cols,wrong[:3]):
            with col:
                with st.container(border=True):
                    image_render(dataset_dir,record["image"])
                    st.markdown(chip(record["outcome"]),unsafe_allow_html=True)
                    st.markdown(f"Actual: `{record['truth']}` · Predicted: `{record['prediction']}`")
                    st.caption(record["image"][:46])
        st.caption("Open the Evidence Explorer to inspect these and all other model decisions in detail.")
    else:
        st.success("No false positives or false negatives among this model's decisive predictions for the selected scope.")


def comparison(dataset_dir, labels, runs, items, scope):
    st.markdown('<p class="mini-kicker">SIDE-BY-SIDE ANALYSIS</p>',unsafe_allow_html=True)
    st.subheader("Compare models on the same image")
    if len(runs) < 2:
        st.info("At least two model prediction CSVs are needed for comparison.")
        return
    names=list(runs)
    a,b=st.columns(2)
    with a: model_a=st.selectbox("Model A",names,index=0)
    with b: model_b=st.selectbox("Model B",names,index=1 if len(names)>1 else 0)
    records_a=full_image_rows(labels,runs[model_a],scope,items)
    records_b=full_image_rows(labels,runs[model_b],scope,items)
    map_a={r["image"]:r for r in records_a}
    map_b={r["image"]:r for r in records_b}
    relevant_images=[r["image"] for r in records_a]
    compare_only=st.checkbox("Only show images where models disagree",value=True)
    if compare_only:
        relevant_images=[x for x in relevant_images if map_a[x]["prediction"]!=map_b[x]["prediction"]]
    if not relevant_images:
        st.info("No different predictions found between those models for this scope. Untick 'Only show images where models disagree' to inspect matching predictions.")
        return
    name=st.selectbox("Select evaluation image", relevant_images,
                      format_func=lambda x: f"{x[:55]} · {map_a[x]['outcome']} vs {map_b[x]['outcome']}")
    st.caption(name)
    img_col,left,right=st.columns([1.15,1,1],gap="medium")
    with img_col:
        image_render(dataset_dir,name)
        st.markdown(f"**Verified ground truth:** `{map_a[name]['truth']}`")
    for col,model,r in ((left,model_a,map_a[name]),(right,model_b,map_b[name])):
        with col:
            st.markdown(f"#### {model}")
            st.markdown(chip(r["outcome"]),unsafe_allow_html=True)
            st.markdown(f"**Prediction:** `{r['prediction']}`")
            st.markdown(f"**Request time:** {seconds_fmt((r['model_row'] or {}).get('seconds'))}")
            show_ppe_detail(r["label_row"],r["model_row"],items)


def ground_truth_gallery(dataset_dir,labels,items):
    st.subheader("Browse verified images")
    st.caption("These are real benchmark photographs with manually reviewed PPE labels. For V2, model predictions will appear after you add your saved model CSVs.")
    choice=st.selectbox("Ground truth filter", ["All images","Helmet violation","Vest violation","Boots violation","Any violation","Any unclear"])
    filtered=[]
    for label in labels:
        truth=[label.get(f"verified_{item}","") for item in items]
        if choice=="All images" or (choice=="Any violation" and "yes" in truth) or (choice=="Any unclear" and "unclear" in truth) or (choice=="Helmet violation" and label.get("verified_helmet")=="yes") or (choice=="Vest violation" and label.get("verified_vest")=="yes") or (choice=="Boots violation" and label.get("verified_boots")=="yes"):
            filtered.append(label)
    st.caption(f"{len(filtered)} verified images match the selection")
    if not filtered: return
    selected=st.selectbox("Inspect verified image", [r["image"] for r in filtered])
    row=next(x for x in filtered if x["image"]==selected)
    col1,col2=st.columns([1.25,1])
    with col1: image_render(dataset_dir,selected)
    with col2:
        st.markdown("**Verified PPE labels**")
        st.dataframe(pd.DataFrame([{"PPE":SCOPES[item],"Violation label":row.get(f"verified_{item}","unclear")} for item in items]), hide_index=True,use_container_width=True)
        if row.get("notes"): st.info("Reviewer note: "+row["notes"])
        if row.get("source_url"): st.markdown(f"Dataset source: {row['source_url']}")
        st.caption("Label convention: yes = violation; no = no visible violation; unclear = cannot reliably determine.")


def methodology(dataset_dir,items):
    st.markdown('<p class="mini-kicker">HOW TO READ THE RESULTS</p>',unsafe_allow_html=True)
    st.subheader("Interpretation and reproducibility")
    st.markdown("""
    **Positive class = PPE violation.** Each image is scored once per scope. Overall PPE status is a violation if at least one required category is definitely missing. A compliant image must have every required item assessed as present. Otherwise, when no definite violation is visible, the status is unclear.

    | Outcome | Meaning for a workplace safety application |
    | --- | --- |
    | **TP** | Actual PPE violation correctly flagged |
    | **TN** | Compliant image correctly cleared |
    | **FP** | Unnecessary alert on a compliant image |
    | **FN** | Real violation missed — important safety risk |
    | **Unclear** | Model could not make a definite decision |
    | **Error** | Invalid response, empty JSON, timeout or other analysis failure |

    **Accuracy** = (TP + TN) / (TP + TN + FP + FN).  
    **Precision** = TP / (TP + FP). **Recall** = TP / (TP + FN).  
    **F1** balances precision and recall. **Coverage** measures decisive predictions among binary-labelled images.  
    Values are undefined when the relevant denominator is zero; they are not automatically 0%.
    """)
    st.markdown("**Data provenance**")
    if len(items)==2:
        st.markdown("Original benchmark: 60 manually verified Roboflow [Construction Site Safety v30](https://universe.roboflow.com/roboflow-universe-projects/construction-site-safety/dataset/30) images. Source dataset page states CC BY 4.0. The image files and prediction CSVs come from your previously supplied project ZIP.")
    else:
        st.markdown("Boots benchmark: 68 manually verified images selected from *PPE Detection v1* ([Roboflow](https://universe.roboflow.com/testcasque/ppe-detection-qlq3d/dataset/1); dataset metadata lists CC BY 4.0) and *Vest-Boots v6* ([Roboflow](https://universe.roboflow.com/epidataset-fnaft/vest-boots/dataset/6); metadata lists Public Domain). Excluded images are not displayed or scored.")
    st.warning("Photographs cannot confirm certified safety footwear or the precise PPE requirements of a worksite. Treat these labels as a visual benchmark, not legal or safety certification. Dataset licences as stated by publishers do not independently guarantee the rights to every underlying image.")
    st.markdown("**Privacy and data handling**")
    st.markdown("This viewer reads CSV and image files only. It does **not** contact Ollama or send data to an AI service. If deployed online, browsers will receive the images; consider access control, dataset permissions and whether your supervisor should have private access.")
    st.markdown("**Adding future results**")
    st.code(f"data/{dataset_dir.name}/predictions/predictions_<model>.csv", language="text")
    st.markdown("Copy new per-image CSVs into that folder, then refresh the app. The CSV must include `image`, `model`, `predicted`, and `pred_helmet`/`pred_vest`/`pred_boots` as applicable. Model runs on different images or with different prompts should be treated as separate benchmarks.")


# Sidebar controls
st.sidebar.markdown("### 🦺 PPE evaluation")
st.sidebar.caption("Browse real images and saved zero-shot VLM results")
dataset_key=st.sidebar.selectbox("Benchmark",list(DATASETS),format_func=lambda k:DATASETS[k]["title"])
dataset_dir=DATA_DIR/dataset_key
config=DATASETS[dataset_key]
items=config["items"]
labels=reviewed_images(dataset_dir)
runs,warnings=model_runs(dataset_dir)
model_list=list(runs)
view=st.sidebar.radio("Page",["Overview","Evidence Explorer","Model vs Model","Ground-truth gallery","Methodology"],index=0)
scope_choices=["overall",*items]
scope=st.sidebar.selectbox("PPE category",scope_choices,format_func=lambda x:SCOPES[x])
preferred=st.sidebar.selectbox("Model",model_list, index=(model_list.index('qwen3.8:27b') if 'qwen3.8:27b' in model_list else 0)) if model_list else None
st.sidebar.divider()
st.sidebar.metric("Verified images",len(labels))
st.sidebar.metric("Model runs available",len(runs))
st.sidebar.caption("No retraining, model downloads or GPU required to view saved results.")
if warnings:
    with st.sidebar.expander("Data warnings"):
        for w in warnings: st.warning(w)

st.markdown('<p class="mini-kicker">PPE SAFETY MONITORING · RESEARCH EVALUATION</p>', unsafe_allow_html=True)
st.title("Vision-Language Model Evaluation")
st.markdown(f"**{config['title']}** — {config['description']}")
st.caption(f"{len(labels)} verified photographs · {len(runs)} saved model runs · Scope: {SCOPES[scope]}")

if view=="Overview":
    overview(dataset_dir,labels,runs,items,scope,preferred)
    if not runs:
        st.divider(); ground_truth_gallery(dataset_dir,labels,items)
elif view=="Evidence Explorer":
    if not runs:
        st.info("This benchmark has verified images but no saved predictions yet.")
        ground_truth_gallery(dataset_dir,labels,items)
    else:
        rows=evidence_rows(labels,runs[preferred],scope,items)
        explorer(rows,dataset_dir,labels,items,preferred,scope)
elif view=="Model vs Model":
    comparison(dataset_dir,labels,runs,items,scope)
elif view=="Ground-truth gallery":
    truth_summary(labels,items)
    ground_truth_gallery(dataset_dir,labels,items)
else:
    methodology(dataset_dir,items)

st.divider()
st.caption("PPE Model Evaluation Viewer · Read-only reference dashboard · Dataset versions are kept separate to prevent misleading comparisons")
