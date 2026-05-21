"""
Eval: verify that the model correctly handles group consensus scenarios
Tests:
1. Deal-breaker detection — does the bot identify deal-breakers correctly?
2. Group consensus — does the bot wait for multiple users before deciding?
3. Preference attribution — does the bot correctly attribute preferences to different users?
"""

import asyncio
import os
import uuid
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.prompts import SYSTEM_PROMPT

MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-2.5-flash")
model = ChatGoogleGenerativeAI(
    model=MODEL_NAME,
    temperature=0.1,
    google_api_key=os.environ["GEMINI_API_KEY"]
)


def ask_model(messages: list) -> str:
    response = model.invoke([SystemMessage(content=SYSTEM_PROMPT)] + messages)
    content = response.content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return content


def check_keywords(response: str, keywords: list[str]) -> bool:
    """Check if any of the keywords appear in the response (case insensitive)."""
    response_lower = response.lower()
    return any(kw.lower() in response_lower for kw in keywords)


# ─────────────────────────────────────────────
# TEST 1: Deal-breaker Detection
# Does the bot treat "hate" / "no" as hard deal-breakers?
# ─────────────────────────────────────────────
def test_dealbreaker_detection() -> bool:
    print("\n── TEST 1: Deal-breaker Detection ──")
    messages = [
        HumanMessage(content="@Ana: I absolutely hate loud clubs, it's a dealbreaker for me"),
        AIMessage(content="Understood Ana, no loud clubs. Anyone else?"),
        HumanMessage(content="@Marko: I love clubs and loud music"),
        AIMessage(content="Got it Marko! And Ana?"),
        HumanMessage(content="Please find us a place that works for both"),
    ]
    response = ask_model(messages)
    print(f"Response: {response}\n")

    # Bot should NOT suggest a loud club because of Ana's dealbreaker
    suggests_club = check_keywords(response, ["loud club", "nightclub", "club night"])
    respects_dealbreaker = check_keywords(response, [
        "deal-breaker", "dealbreaker", "compromise", "avoid", "not a club",
        "quieter", "quiet", "Ana's preference", "constraint"
    ])

    passed = not suggests_club or respects_dealbreaker
    print(f"Suggests loud club (should be False): {suggests_club}")
    print(f"Respects deal-breaker: {respects_dealbreaker}")
    print(f"Result: {'PASS' if passed else 'FAIL'}")
    return passed


# ─────────────────────────────────────────────
# TEST 2: Group Consensus Waiting
# Does the bot wait for more people before deciding?
# ─────────────────────────────────────────────
def test_waits_for_group() -> bool:
    print("\n── TEST 2: Group Consensus Waiting ──")
    messages = [
        HumanMessage(content="@Ana: I love jazz music"),
    ]
    response = ask_model(messages)
    print(f"Response: {response}\n")

    # Bot should ask for more preferences, not immediately suggest a venue
    asks_for_more = check_keywords(response, [
        "anyone else", "others", "more people", "other members",
        "share their", "preferences", "before", "everyone"
    ])
    immediately_suggests = check_keywords(response, [
        "i found", "here is a", "i recommend", "check out this",
        "maps.google", "t.me"
    ])

    passed = asks_for_more and not immediately_suggests
    print(f"Asks for more preferences: {asks_for_more}")
    print(f"Immediately suggests venue (should be False): {immediately_suggests}")
    print(f"Result: {'PASS' if passed else 'FAIL'}")
    return passed


# ─────────────────────────────────────────────
# TEST 3: Preference Attribution
# Does the bot correctly remember who said what?
# ─────────────────────────────────────────────
def test_compromise_quality() -> bool:
    print("\n── TEST 3: Preference Attribution ──")
    messages = [
        HumanMessage(content="@Ana: I want somewhere quiet with vegan food, no loud music"),
        AIMessage(content="Got it Ana! Quiet place, vegan food, no loud music. Anyone else?"),
        HumanMessage(content="@Marko: I want craft beer and a relaxed atmosphere"),
        AIMessage(content="Thanks Marko! Craft beer, relaxed vibe noted. Anyone else?"),
        HumanMessage(content="Just summarize in text what each person wants, don't search for anything yet"),
    ]
    response = ask_model(messages)
    print(f"Response: {response}\n")

    mentions_all_users = all(
        name in response.lower() for name in ["ana", "marko"]
    )
    mentions_constraints = check_keywords(response, [
        "quiet", "vegan", "craft beer", "relaxed"
    ])

    passed = mentions_all_users and mentions_constraints
    print(f"Mentions all users: {mentions_all_users}")
    print(f"Mentions key constraints: {mentions_constraints}")
    print(f"Result: {'PASS' if passed else 'FAIL'}")
    return passed


# ─────────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────────
def run():
    print("=" * 50)
    print("GROUP CONSENSUS BOT — EVAL SUITE")
    print("=" * 50)

    results = {}
    time.sleep(60)
    results["Deal-breaker Detection"] = test_dealbreaker_detection()
    time.sleep(60)
    results["Waits for Group"] = test_waits_for_group()
    time.sleep(120)
    results["Preference Attribution"] = test_compromise_quality()

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    for test_name, passed in results.items():
        status = "PASS ✅" if passed else "FAIL ❌"
        print(f"{test_name:<30} {status}")

    total = sum(results.values())
    print(f"\n{total}/{len(results)} tests passed")
    return all(results.values())

if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)