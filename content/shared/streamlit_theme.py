"""
Streamlit dark-theme CSS injector for CosySim.

Usage (in any Streamlit scene)::

    from content.shared.streamlit_theme import inject_dark_theme
    inject_dark_theme()          # call once at top of page

This injects CSS that converts the default Streamlit light theme
into the CosySim dark theme using the canonical design tokens.
"""
import streamlit as st

_DARK_CSS = """
<style>
/* ── CosySim Dark Theme for Streamlit ──────────────────── */

/* Base: dark background */
.stApp {
    background-color: #0d0d0d !important;
    color: #f0f0f0 !important;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
                 Roboto, Oxygen, Ubuntu, Cantarell, sans-serif !important;
}

/* Main content area */
.main .block-container {
    background-color: #0d0d0d !important;
    color: #f0f0f0 !important;
    max-width: 1200px;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #1a1a1a !important;
    border-right: 1px solid rgba(255, 255, 255, 0.08) !important;
}
section[data-testid="stSidebar"] .stMarkdown,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span {
    color: #f0f0f0 !important;
}

/* Headers */
h1, h2, h3, h4, h5, h6 {
    color: #f0f0f0 !important;
}
h1 {
    background: linear-gradient(135deg, #667eea, #764ba2);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

/* Text */
p, span, li, label, .stMarkdown {
    color: #f0f0f0 !important;
}
.stMarkdown a {
    color: #667eea !important;
}

/* Inputs */
.stTextInput input,
.stTextArea textarea,
.stNumberInput input,
.stSelectbox > div > div,
.stMultiSelect > div > div {
    background-color: #242424 !important;
    color: #f0f0f0 !important;
    border-color: rgba(255, 255, 255, 0.08) !important;
    border-radius: 10px !important;
}
.stTextInput input:focus,
.stTextArea textarea:focus {
    border-color: #667eea !important;
    box-shadow: 0 0 0 1px #667eea !important;
}

/* Buttons */
.stButton > button {
    background: linear-gradient(135deg, #667eea, #764ba2) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 500 !important;
    transition: all 0.2s ease !important;
}
.stButton > button:hover {
    opacity: 0.9 !important;
    transform: translateY(-1px) !important;
}

/* Expanders */
.streamlit-expanderHeader {
    background-color: #1a1a1a !important;
    color: #f0f0f0 !important;
    border-radius: 10px !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
}
.streamlit-expanderContent {
    background-color: #1a1a1a !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-top: none !important;
    border-radius: 0 0 10px 10px !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    background-color: #1a1a1a !important;
    border-radius: 10px !important;
    padding: 4px !important;
    gap: 4px !important;
}
.stTabs [data-baseweb="tab"] {
    color: #a0a0a0 !important;
    border-radius: 8px !important;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, #667eea, #764ba2) !important;
    color: white !important;
}

/* Metric cards */
[data-testid="stMetricValue"] {
    color: #667eea !important;
}
[data-testid="stMetricLabel"] {
    color: #a0a0a0 !important;
}

/* Dataframes / tables */
.stDataFrame {
    border-radius: 10px !important;
    overflow: hidden !important;
}

/* JSON display */
.stJson {
    background-color: #1a1a1a !important;
    border-radius: 10px !important;
}

/* Info/Success/Warning/Error boxes */
.stAlert {
    background-color: #1a1a1a !important;
    border-radius: 10px !important;
}

/* Dividers */
hr {
    border-color: rgba(255, 255, 255, 0.08) !important;
}

/* Scrollbar */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: #0d0d0d;
}
::-webkit-scrollbar-thumb {
    background: #333;
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: #555;
}

/* Selectbox dropdown */
[data-baseweb="popover"] {
    background-color: #242424 !important;
}
[data-baseweb="popover"] li {
    color: #f0f0f0 !important;
}
[data-baseweb="popover"] li:hover {
    background-color: #2e2e2e !important;
}

/* Checkbox / Radio */
.stCheckbox label span,
.stRadio label span {
    color: #f0f0f0 !important;
}

/* Progress bars */
.stProgress > div > div {
    background: linear-gradient(135deg, #667eea, #764ba2) !important;
}

/* ── Utility classes ──────────────────────────────────── */
.cs-card {
    background-color: #1a1a1a;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 12px;
}
.cs-gradient-text {
    background: linear-gradient(135deg, #667eea, #764ba2);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    font-weight: 700;
}
.cs-stat-card {
    background: linear-gradient(135deg, #667eea, #764ba2);
    color: white;
    border-radius: 10px;
    padding: 16px;
    text-align: center;
}
.cs-stat-card h3 { color: white !important; -webkit-text-fill-color: white; margin: 0; }
.cs-stat-card p  { color: rgba(255,255,255,0.8) !important; margin: 4px 0 0; }
</style>
"""


def inject_dark_theme() -> None:
    """Inject the CosySim dark theme CSS into the current Streamlit page."""
    st.markdown(_DARK_CSS, unsafe_allow_html=True)
