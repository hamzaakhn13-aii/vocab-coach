"""
Vocab Coach - fix English spelling and grow your vocabulary with Gemini.
Run locally:  streamlit run app.py
"""

import csv
import io
import os

import streamlit as st

from ai_helper import DEFAULT_MODEL, LEVELS, AIError, analyze_words, make_quiz, parse_words

st.set_page_config(page_title="Vocab Coach", page_icon="📚", layout="centered")


# --------------------------------------------------------------------------
# Session state (the app's memory while the page is open)
# --------------------------------------------------------------------------
def init_state():
    defaults = {
        "results": [],        # results of the latest spell check
        "word_list": {},      # all checked words: {corrected_word_lowercase: result}
        "quiz": [],           # current quiz questions
        "quiz_id": 0,         # changes with every new quiz (keeps radio buttons fresh)
        "quiz_answers": None, # answers after the learner submits
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_secret_key() -> str:
    """Look for the API key in Streamlit secrets or environment variables."""
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
        if key:
            return str(key)
    except Exception:  # no secrets file exists - that is fine
        pass
    return os.environ.get("GEMINI_API_KEY", "")


init_state()

# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Settings")

    secret_key = get_secret_key()
    if secret_key:
        api_key = secret_key
        st.success("API key loaded ✔")
    else:
        api_key = st.text_input(
            "Gemini API key",
            type="password",
            help="Get a free key at https://aistudio.google.com/apikey",
        )

    level = st.selectbox("Your English level", LEVELS, index=1)
    model = st.text_input(
        "Gemini model",
        value=DEFAULT_MODEL,
        help="If you get a 'model not found' error, try gemini-2.5-flash",
    )
    st.caption(f"Words saved this session: {len(st.session_state.word_list)}")

# --------------------------------------------------------------------------
# Main page
# --------------------------------------------------------------------------
st.title("📚 Vocab Coach")
st.write("Type English words — even with spelling mistakes. I will fix them and help you learn better words.")

tab_check, tab_quiz, tab_list = st.tabs(["✍️ Check Words", "🎯 Quiz", "📒 My Word List"])

# ---------------------------- Tab 1: check words ----------------------------
with tab_check:
    text = st.text_area(
        "Your words (separate with commas or new lines, max 15)",
        placeholder="beutiful, recieve, definately, happy",
        height=110,
    )

    if st.button("Check my words", type="primary"):
        words = parse_words(text)
        if not words:
            st.warning("Please type at least one word.")
        else:
            try:
                with st.spinner("Checking with Gemini..."):
                    results = analyze_words(api_key, model, words, level)
                st.session_state.results = results
                for r in results:
                    if r["corrected"]:
                        st.session_state.word_list[r["corrected"].lower()] = r
                # an old quiz no longer matches the word list
                st.session_state.quiz = []
                st.session_state.quiz_answers = None
            except AIError as err:
                st.error(str(err))

    for r in st.session_state.results:
        with st.container(border=True):
            if not r["corrected"]:
                st.error(f"🤔 I could not recognise **{r['original']}**. Please check it and try again.")
                if r["tip"]:
                    st.caption(r["tip"])
                continue

            if r["is_correct"]:
                st.success(f"✅ **{r['corrected']}** is spelled correctly")
            else:
                st.warning(f"❌ {r['original']}  →  ✅ **{r['corrected']}**")

            if r["part_of_speech"]:
                st.caption(r["part_of_speech"])
            if r["meaning"]:
                st.markdown(f"**Meaning:** {r['meaning']}")
            if r["example"]:
                st.markdown(f"**Example:** _{r['example']}_")
            if r["synonyms"]:
                st.markdown("**Similar words:** " + ", ".join(r["synonyms"]))
            if r["better_words"]:
                st.markdown("**Level up with:** " + ", ".join(r["better_words"]))
            if r["tip"]:
                st.info(f"💡 {r['tip']}")

# ------------------------------- Tab 2: quiz --------------------------------
with tab_quiz:
    saved = [r["corrected"] for r in st.session_state.word_list.values()]
    if not saved:
        st.info("Check some words first, then come back here for a quiz.")
    else:
        st.write(f"I will test you on your saved words ({len(saved)}).")
        if st.button("Make a new quiz"):
            try:
                with st.spinner("Writing your quiz..."):
                    st.session_state.quiz = make_quiz(api_key, model, saved[-10:], level)
                st.session_state.quiz_id += 1
                st.session_state.quiz_answers = None
            except AIError as err:
                st.error(str(err))

    quiz = st.session_state.quiz
    if quiz:
        qid = st.session_state.quiz_id
        with st.form(f"quiz_form_{qid}"):
            picked = []
            for i, q in enumerate(quiz):
                picked.append(
                    st.radio(f"{i + 1}. {q['question']}", q["options"], index=None, key=f"q_{qid}_{i}")
                )
            submitted = st.form_submit_button("Submit answers")
        if submitted:
            st.session_state.quiz_answers = picked

        answers = st.session_state.quiz_answers
        if answers is not None:
            score = 0
            for q, chosen in zip(quiz, answers):
                right = q["options"][q["answer_index"]]
                if chosen == right:
                    score += 1
                    st.success(f"✅ {q['question']}  — **{right}**")
                else:
                    st.error(f"❌ {q['question']}  — correct answer: **{right}**")
                if q["explanation"]:
                    st.caption(q["explanation"])
            st.subheader(f"Score: {score} / {len(quiz)}")

# --------------------------- Tab 3: my word list ----------------------------
with tab_list:
    words_saved = list(st.session_state.word_list.values())
    if not words_saved:
        st.info("Your corrected words will appear here.")
    else:
        rows = [
            {
                "Word": r["corrected"],
                "You typed": r["original"],
                "Meaning": r["meaning"],
                "Example": r["example"],
                "Level up with": ", ".join(r["better_words"]),
            }
            for r in words_saved
        ]
        st.dataframe(rows, hide_index=True)

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        st.download_button("⬇️ Download as CSV", buffer.getvalue(), "my_words.csv", "text/csv")

        if st.button("Clear my list"):
            st.session_state.word_list = {}
            st.session_state.quiz = []
            st.session_state.quiz_answers = None
            st.rerun()

st.divider()
st.caption("Built with Streamlit + Google Gemini. AI can make mistakes — double-check important words.")
